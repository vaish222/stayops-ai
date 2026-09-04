"""Phase 6 graph with a deterministic risk/action gate after synthesis."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, StateGraph

from src.agents import RequestRouter
from src.graph.parallel_workflow import SPECIALIST_FINDING_FIELDS, SpecialistRunner
from src.graph.state import StayOpsState, WorkflowError
from src.graph.synthesis_workflow import (
    SynthesisRunner,
    _create_phase_5_graph_builder,
)
from src.models import (
    HumanReviewReason,
    ReviewReasonCode,
    RiskGateOutput,
    SpecialistName,
)
from src.safety import RiskActionGate
from src.tools import FailureSimulator, SimulatedOperationsStore
from src.tools.read_tools import DEFAULT_DATA_DIR


class GateRunner(Protocol):
    def evaluate(self, payload: dict[str, Any]) -> RiskGateOutput: ...


def risk_gate_node(
    state: StayOpsState,
    *,
    gate: GateRunner | None = None,
) -> dict[str, Any]:
    """Evaluate structured findings/actions and return review state and reasons."""

    configured_gate = gate or RiskActionGate()
    specialist_findings = [
        finding
        for field_name in SPECIALIST_FINDING_FIELDS.values()
        for finding in state[field_name]  # type: ignore[literal-required]
    ]
    payload = {
        "write_requested": state["write_requested"],
        "synthesis_complete": state["synthesis_complete"],
        "unavailable_sources": state["unavailable_sources"],
        "specialist_findings": specialist_findings,
        "prioritized_findings": state["operational_findings"],
        "proposed_actions": state["proposed_actions"],
    }
    try:
        output = configured_gate.evaluate(payload)
    except Exception as exc:
        message = f"Risk gate evaluation failed: {type(exc).__name__}: {exc}"
        reason = HumanReviewReason(
            code=ReviewReasonCode.GATE_EVALUATION_ERROR,
            message="Risk gate evaluation failed; human review is required by default.",
            source_ids=["risk_gate:evaluation_error"],
        )
        error = WorkflowError(
            stage="risk_gate_execution",
            code="risk_gate_failure",
            message=message,
            component="risk_action_gate",
            retryable=False,
            details={"exception_type": type(exc).__name__},
        )
        return {
            "requires_human_review": True,
            "review_reasons": [reason.model_dump(mode="json")],
            "operational_warnings": [],
            "risk_gate_evaluated": False,
            "errors": [error],
        }
    return {
        "requires_human_review": output.requires_human_review,
        "review_reasons": [
            reason.model_dump(mode="json") for reason in output.reasons
        ],
        "operational_warnings": [
            warning.model_dump(mode="json") for warning in output.advisories
        ],
        "risk_gate_evaluated": True,
    }


def _create_phase_6_graph_builder(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    runtime_store: SimulatedOperationsStore | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
    gate_runner: GateRunner | None = None,
) -> StateGraph:
    """Build Phase 5 plus the deterministic gate, without a terminal edge."""

    configured_gate = gate_runner or RiskActionGate()
    graph_builder = _create_phase_5_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        runtime_store=runtime_store,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
    )

    def gate_node(state: StayOpsState) -> dict[str, Any]:
        return risk_gate_node(state, gate=configured_gate)

    graph_builder.add_node("risk_action_gate", gate_node)
    graph_builder.add_edge("operations_synthesizer", "risk_action_gate")
    return graph_builder


def build_phase_6_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    runtime_store: SimulatedOperationsStore | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
    gate_runner: GateRunner | None = None,
):
    """Compile Phase 6 and stop immediately after the deterministic gate."""

    graph_builder = _create_phase_6_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        runtime_store=runtime_store,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
        gate_runner=gate_runner,
    )
    graph_builder.add_edge("risk_action_gate", END)
    return graph_builder.compile(name="stayops_phase_6_risk_action_gate")
