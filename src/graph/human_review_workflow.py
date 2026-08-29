"""Phase 7 checkpointed human review after deterministic risk gating."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from src.agents import RequestRouter
from src.graph.parallel_workflow import SpecialistRunner
from src.graph.risk_workflow import GateRunner, _create_phase_6_graph_builder
from src.graph.state import StayOpsState
from src.graph.synthesis_workflow import SynthesisRunner
from src.models import (
    HumanDecisionRecord,
    HumanReviewRequest,
    HumanReviewResponse,
    ProposedAction,
    ReviewDecision,
    SpecialistName,
)
from src.tools import FailureSimulator
from src.tools.read_tools import DEFAULT_DATA_DIR


def _review_request(
    state: StayOpsState,
    *,
    validation_error: str | None = None,
) -> dict[str, Any]:
    prior_decision = state["human_decision"] or {}
    reconfirming_edit = prior_decision.get("decision") == ReviewDecision.EDIT
    request = HumanReviewRequest(
        request_id=state["request_id"],
        question=(
            "Reconfirm the edited proposal: approve, edit again, or reject?"
            if reconfirming_edit
            else "Review the proposal and evidence: approve, edit, or reject?"
        ),
        proposed_actions=state["proposed_actions"],
        findings=state["operational_findings"],
        review_reasons=state["review_reasons"],
        validation_error=validation_error,
    )
    return request.model_dump(mode="json")


def _selected_actions(
    actions: list[ProposedAction],
    action_id: str | None,
) -> list[ProposedAction]:
    if action_id is None:
        return actions
    selected = [action for action in actions if action.action_id == action_id]
    if not selected:
        raise ValueError(f"unknown proposed action_id: {action_id}")
    return selected


def human_review_node(state: StayOpsState) -> dict[str, Any]:
    """Pause for a validated decision; edits always require another pause."""

    validation_error: str | None = None
    while True:
        raw_response = interrupt(
            _review_request(state, validation_error=validation_error)
        )
        try:
            response = HumanReviewResponse.model_validate(raw_response)
            actions = [
                ProposedAction.model_validate(action)
                for action in state["proposed_actions"]
            ]
            selected_actions = _selected_actions(actions, response.action_id)
            if response.decision == ReviewDecision.EDIT and not selected_actions:
                raise ValueError("no proposed action is available to edit")
        except (ValidationError, ValueError) as exc:
            validation_error = f"Invalid human decision: {exc}"
            continue
        break

    if response.decision == ReviewDecision.EDIT:
        selected = selected_actions[0]
        updated_parameters = selected.parameters
        if "message" in selected.parameters:
            updated_parameters = {"message": response.edited_description}
        edited = selected.model_copy(
            update={
                "description": response.edited_description,
                "parameters": updated_parameters,
            }
        )
        updated_actions = [
            edited if action.action_id == edited.action_id else action
            for action in actions
        ]
        decision = HumanDecisionRecord(
            decision=ReviewDecision.EDIT,
            action_ids=[edited.action_id],
            review_complete=False,
            reviewed_actions=[edited],
            edited_description=edited.description,
        )
        return {
            "proposed_actions": [
                action.model_dump(mode="json") for action in updated_actions
            ],
            "human_decision": decision.model_dump(mode="json"),
        }

    decision = HumanDecisionRecord(
        decision=response.decision,
        action_ids=[action.action_id for action in selected_actions],
        review_complete=True,
        reviewed_actions=selected_actions,
    )
    return {"human_decision": decision.model_dump(mode="json")}


def _route_after_risk_gate(state: StayOpsState) -> str:
    return "review" if state["requires_human_review"] else "complete"


def _route_after_human_review(state: StayOpsState) -> str:
    decision = state["human_decision"] or {}
    if decision.get("decision") == ReviewDecision.EDIT:
        return "reconfirm"
    if decision.get("decision") == ReviewDecision.APPROVE:
        return "approved"
    return "rejected"


def _create_phase_7_graph_builder(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
    gate_runner: GateRunner | None = None,
) -> StateGraph:
    """Build Phase 7 through human review, without its completion routes."""

    graph_builder = _create_phase_6_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
        gate_runner=gate_runner,
    )
    graph_builder.add_node("human_review", human_review_node)
    graph_builder.add_conditional_edges(
        "risk_action_gate",
        _route_after_risk_gate,
        {"review": "human_review", "complete": END},
    )
    return graph_builder


def build_phase_7_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
    gate_runner: GateRunner | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile Phase 7 with resumable review and no action execution node."""

    graph_builder = _create_phase_7_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
        gate_runner=gate_runner,
    )
    graph_builder.add_conditional_edges(
        "human_review",
        _route_after_human_review,
        {"reconfirm": "human_review", "approved": END, "rejected": END},
    )
    configured_checkpointer = (
        checkpointer if checkpointer is not None else InMemorySaver()
    )
    return graph_builder.compile(
        name="stayops_phase_7_human_review",
        checkpointer=configured_checkpointer,
    )
