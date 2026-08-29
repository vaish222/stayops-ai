"""Phase 8 graph for approval-authorized simulated action execution."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

from src.agents import RequestRouter
from src.graph.human_review_workflow import (
    _create_phase_7_graph_builder,
    _route_after_human_review,
)
from src.graph.parallel_workflow import SpecialistRunner
from src.graph.risk_workflow import GateRunner
from src.graph.response_workflow import ResponseRunner, response_generator_node
from src.graph.state import StayOpsState, WorkflowError
from src.graph.synthesis_workflow import SynthesisRunner
from src.models import (
    CleaningSchedule,
    GuestMessage,
    HumanDecisionRecord,
    MaintenanceTicket,
    ProposedAction,
    ReviewDecision,
    SpecialistName,
)
from src.tools import (
    ApprovalAuthority,
    FailureSimulator,
    SimulatedOperationsStore,
    WRITE_TOOL_RUNNERS,
)
from src.tools.read_tools import DEFAULT_DATA_DIR


def execute_approved_actions_node(
    state: StayOpsState,
    *,
    authority: ApprovalAuthority,
    runtime_store: SimulatedOperationsStore | None = None,
) -> dict[str, Any]:
    """Mint exact-action capabilities and invoke only their matching write tools."""

    decision = HumanDecisionRecord.model_validate(state["human_decision"])
    if decision.decision != ReviewDecision.APPROVE or not decision.review_complete:
        return {
            "approval_grants": state["approval_grants"],
            "action_attempts": state["action_attempts"],
            "executed_actions": state["executed_actions"],
        }

    grants: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    errors: list[WorkflowError] = []
    for reviewed_action in decision.reviewed_actions:
        action = ProposedAction.model_validate(reviewed_action)
        if action.tool_name is None:
            continue
        try:
            grant = authority.issue(
                request_id=state["request_id"],
                action=action,
                decision=decision,
            )
            runner = WRITE_TOOL_RUNNERS[action.tool_name]
            result = runner(
                action=action,
                approval_token=grant.token,
                request_id=state["request_id"],
                authority=authority,
            )
        except Exception as exc:
            errors.append(
                WorkflowError(
                    stage="action_execution",
                    code="write_execution_failure",
                    message=f"Simulated write failed: {type(exc).__name__}: {exc}",
                    component="approval_protected_write_tools",
                    retryable=False,
                    details={"exception_type": type(exc).__name__},
                )
            )
            continue
        grants.append(grant.model_dump(mode="json"))
        attempts.append(result.attempt.model_dump(mode="json"))
        if result.execution is not None:
            if runtime_store is not None:
                runtime_store.record_execution(
                    request_id=state["request_id"],
                    action=action,
                    execution=result.execution,
                )
            executions.append(result.execution.model_dump(mode="json"))

    reviewed_action_ids = set(decision.action_ids)
    update: dict[str, Any] = {
        "proposed_actions": [
            action
            for action in state["proposed_actions"]
            if action["action_id"] not in reviewed_action_ids
        ],
        "approval_grants": [*state["approval_grants"], *grants],
        "action_attempts": [*state["action_attempts"], *attempts],
        "executed_actions": [*state["executed_actions"], *executions],
    }
    if runtime_store is not None and executions:
        guest_messages = runtime_store.apply_guest_messages(
            [
                GuestMessage.model_validate(item)
                for item in state["guest_message_context"].values()
            ]
        )
        cleanings = runtime_store.apply_cleanings(
            [
                CleaningSchedule.model_validate(item)
                for item in state["cleaning_context"].values()
            ]
        )
        maintenance = runtime_store.apply_maintenance(
            [
                MaintenanceTicket.model_validate(item)
                for item in state["maintenance_context"].values()
            ]
        )
        update.update(
            {
                "guest_message_context": {
                    item.id: item.model_dump(mode="json") for item in guest_messages
                },
                "cleaning_context": {
                    item.id: item.model_dump(mode="json") for item in cleanings
                },
                "maintenance_context": {
                    item.id: item.model_dump(mode="json") for item in maintenance
                },
            }
        )
    if errors:
        update["errors"] = errors
    return update


def record_rejected_action_node(state: StayOpsState) -> dict[str, Any]:
    """Remove only the reviewed card so the remaining cards stay pending."""

    decision = HumanDecisionRecord.model_validate(state["human_decision"])
    rejected_ids = set(decision.action_ids)
    return {
        "proposed_actions": [
            action
            for action in state["proposed_actions"]
            if action["action_id"] not in rejected_ids
        ]
    }


def _route_remaining_actions(state: StayOpsState) -> str:
    return "review" if state["proposed_actions"] else "complete"


def build_phase_8_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    runtime_store: SimulatedOperationsStore | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
    gate_runner: GateRunner | None = None,
    response_runner: ResponseRunner | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    approval_authority: ApprovalAuthority | None = None,
):
    """Compile Phase 8 with one-time approval-protected simulated writes."""

    authority = (
        approval_authority
        if approval_authority is not None
        else ApprovalAuthority()
    )
    graph_builder = _create_phase_7_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        runtime_store=runtime_store,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
        gate_runner=gate_runner,
        completion_target="response_generator",
    )

    def execute_node(state: StayOpsState) -> dict[str, Any]:
        return execute_approved_actions_node(
            state,
            authority=authority,
            runtime_store=runtime_store,
        )

    def response_node(state: StayOpsState) -> dict[str, Any]:
        return response_generator_node(state, generator=response_runner)

    graph_builder.add_node("execute_approved_actions", execute_node)
    graph_builder.add_node("record_rejected_action", record_rejected_action_node)
    graph_builder.add_node("response_generator", response_node)
    graph_builder.add_conditional_edges(
        "human_review",
        _route_after_human_review,
        {
            "reconfirm": "human_review",
            "approved": "execute_approved_actions",
            "rejected": "record_rejected_action",
        },
    )
    graph_builder.add_conditional_edges(
        "execute_approved_actions",
        _route_remaining_actions,
        {"review": "human_review", "complete": "response_generator"},
    )
    graph_builder.add_conditional_edges(
        "record_rejected_action",
        _route_remaining_actions,
        {"review": "human_review", "complete": "response_generator"},
    )
    graph_builder.add_edge("response_generator", END)
    configured_checkpointer = (
        checkpointer if checkpointer is not None else InMemorySaver()
    )
    return graph_builder.compile(
        name="stayops_phase_8_approval_protected_actions",
        checkpointer=configured_checkpointer,
    )
