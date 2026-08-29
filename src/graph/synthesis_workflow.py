"""Phase 5 graph: parallel specialists followed by one deferred synthesizer."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

from src.agents import (
    BookingAgent,
    GuestAgent,
    MaintenanceAgent,
    OperationsSynthesizer,
    RequestRouter,
    TurnoverAgent,
)
from src.graph.parallel_workflow import (
    SPECIALIST_FINDING_FIELDS,
    SPECIALIST_NODE_NAMES,
    SpecialistRunner,
    _run_specialist_node,
    load_context_node,
)
from src.graph.routing import request_router_node
from src.graph.state import StayOpsState, WorkflowError
from src.models import OperationsSynthesisOutput, SpecialistName
from src.tools import FailureSimulator
from src.tools.read_tools import DEFAULT_DATA_DIR


class SynthesisRunner(Protocol):
    def invoke(self, payload: dict[str, Any]) -> OperationsSynthesisOutput: ...


def operations_synthesizer_node(
    state: StayOpsState,
    *,
    synthesizer: SynthesisRunner | None = None,
) -> dict[str, Any]:
    """Synthesize only specialist finding fields; raw context is not passed."""

    runner = synthesizer or OperationsSynthesizer()
    structured_findings = [
        finding
        for field_name in SPECIALIST_FINDING_FIELDS.values()
        for finding in state[field_name]  # type: ignore[literal-required]
    ]
    try:
        output = runner.invoke({"specialist_findings": structured_findings})
    except Exception as exc:
        message = f"Operations synthesis failed: {type(exc).__name__}: {exc}"
        error = WorkflowError(
            stage="synthesis_execution",
            code="synthesis_failure",
            message=message,
            component="operations_synthesizer",
            retryable=False,
            details={"exception_type": type(exc).__name__},
        )
        return {
            "overall_status": "",
            "action_proposed": False,
            "operational_findings": [],
            "priority_items": [],
            "proposed_actions": [],
            "final_response": "Operations synthesis is unavailable.",
            "errors": [error],
        }

    serialized_findings = [
        finding.model_dump(mode="json") for finding in output.prioritized_findings
    ]
    return {
        "overall_status": output.overall_status.value,
        "action_proposed": output.action_proposed,
        "operational_findings": serialized_findings,
        "priority_items": [
            finding
            for finding in serialized_findings
            if finding["requires_attention"]
        ],
        "proposed_actions": [
            action.model_dump(mode="json") for action in output.proposed_actions
        ],
        "final_response": output.briefing,
    }


def build_phase_5_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
):
    """Compile Phase 4 fan-out plus a deferred, evidence-only synthesis node."""

    configured_router = router or RequestRouter()
    configured_synthesizer = synthesis_runner or OperationsSynthesizer()
    runners: dict[SpecialistName, SpecialistRunner] = {
        SpecialistName.BOOKING: BookingAgent(),
        SpecialistName.GUEST: GuestAgent(),
        SpecialistName.TURNOVER: TurnoverAgent(),
        SpecialistName.MAINTENANCE: MaintenanceAgent(),
    }
    if specialist_runners:
        runners.update(specialist_runners)

    def route_node(state: StayOpsState) -> dict[str, str | list[str] | bool | None]:
        return request_router_node(
            state,
            router=configured_router,
            reference_date=reference_date,
        )

    def context_node(state: StayOpsState) -> dict[str, Any]:
        return load_context_node(
            state,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        )

    def route_to_specialists(state: StayOpsState) -> Sequence[str]:
        return [
            SPECIALIST_NODE_NAMES[SpecialistName(name)]
            for name in state["selected_specialists"]
        ]

    def synthesis_node(state: StayOpsState) -> dict[str, Any]:
        return operations_synthesizer_node(
            state,
            synthesizer=configured_synthesizer,
        )

    graph_builder = StateGraph(StayOpsState)
    graph_builder.add_node("request_router", route_node)
    graph_builder.add_node("load_context", context_node)
    for specialist, node_name in SPECIALIST_NODE_NAMES.items():
        runner = runners[specialist]

        def specialist_node(
            state: StayOpsState,
            selected_specialist: SpecialistName = specialist,
            selected_runner: SpecialistRunner = runner,
        ) -> dict[str, Any]:
            return _run_specialist_node(
                state,
                specialist=selected_specialist,
                runner=selected_runner,
            )

        graph_builder.add_node(node_name, specialist_node)
    graph_builder.add_node(
        "operations_synthesizer",
        synthesis_node,
        defer=True,
    )

    graph_builder.add_edge(START, "request_router")
    graph_builder.add_edge("request_router", "load_context")
    graph_builder.add_conditional_edges(
        "load_context",
        route_to_specialists,
        list(SPECIALIST_NODE_NAMES.values()),
    )
    for node_name in SPECIALIST_NODE_NAMES.values():
        graph_builder.add_edge(node_name, "operations_synthesizer")
    graph_builder.add_edge("operations_synthesizer", END)
    return graph_builder.compile(name="stayops_phase_5_operations_synthesis")
