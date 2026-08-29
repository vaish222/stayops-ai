"""Phase 5 graph: parallel specialists followed by one deferred synthesizer."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

from src.agents import (
    BookingAgent,
    GuestAgent,
    MaintenanceAgent,
    RequestRouter,
    TurnoverAgent,
)
from src.agents.llm_operations_synthesizer import LLMSynthesisUnavailable
from src.graph.parallel_workflow import (
    SPECIALIST_FINDING_FIELDS,
    SPECIALIST_NODE_NAMES,
    SpecialistRunner,
    _run_specialist_node,
    load_context_node,
)
from src.graph.routing import request_router_node
from src.graph.state import StayOpsState, WorkflowError
from src.llm.factory import build_synthesis_runner
from src.models import (
    OperationsSynthesisOutput,
    SpecialistName,
    SynthesisExecutionResult,
    SynthesisInvocation,
    SynthesisRunMetadata,
    SynthesisRunStatus,
)
from src.tools import FailureSimulator, SimulatedOperationsStore
from src.tools.read_tools import DEFAULT_DATA_DIR


class SynthesisRunner(Protocol):
    def invoke(
        self,
        payload: SynthesisInvocation | dict[str, Any],
    ) -> SynthesisExecutionResult | OperationsSynthesisOutput: ...


def _incomplete_analysis_warning(unavailable_sources: list[str]) -> str:
    readable_sources = ", ".join(
        source.removeprefix("get_").replace("_", " ")
        for source in unavailable_sources
    )
    return (
        f"Analysis incomplete: {readable_sources} remained unavailable after retry. "
        "Findings are partial; absence of findings is not an all-clear."
    )


def operations_synthesizer_node(
    state: StayOpsState,
    *,
    synthesizer: SynthesisRunner | None = None,
) -> dict[str, Any]:
    """Synthesize only specialist finding fields; raw context is not passed."""

    runner = synthesizer or build_synthesis_runner()
    structured_findings = [
        finding
        for field_name in SPECIALIST_FINDING_FIELDS.values()
        for finding in state[field_name]  # type: ignore[literal-required]
    ]
    invocation = SynthesisInvocation(
        specialist_findings=structured_findings,
        property_scope=state["property_scope"],
        date_scope=state["date_scope"],
        specialist_errors=[
            dict(error)
            for error in state["errors"]
            if error.get("stage")
            in {"context_loading", "specialist_execution"}
        ],
    )
    started_at = perf_counter_ns()
    try:
        result = runner.invoke(invocation)
        if isinstance(result, SynthesisExecutionResult):
            output = result.output
            metadata = result.metadata
        else:
            # Preserve the existing injection seam for tests/custom deterministic runners.
            output = OperationsSynthesisOutput.model_validate(result)
            metadata = SynthesisRunMetadata(
                mode="deterministic",
                status=SynthesisRunStatus.COMPLETED,
                latency_ms=round((perf_counter_ns() - started_at) / 1_000_000, 3),
                prioritized_finding_count=len(output.prioritized_findings),
            )
    except Exception as exc:
        metadata = (
            exc.metadata
            if isinstance(exc, LLMSynthesisUnavailable)
            else SynthesisRunMetadata(
                mode="deterministic",
                status=SynthesisRunStatus.FAILED,
                latency_ms=round((perf_counter_ns() - started_at) / 1_000_000, 3),
                prioritized_finding_count=0,
                error_code="synthesis_failure",
                error_type=type(exc).__name__,
            )
        )
        error = WorkflowError(
            stage="synthesis_execution",
            code=metadata.error_code or "synthesis_failure",
            message="Operations synthesis could not be completed.",
            component="operations_synthesizer",
            retryable=False,
            details={
                "mode": metadata.mode,
                "provider": metadata.provider,
                "model": metadata.model,
                "status": metadata.status.value,
                "fallback_used": metadata.fallback_used,
                "exception_type": metadata.error_type or type(exc).__name__,
            },
        )
        response = "Operations synthesis is unavailable."
        if state["unavailable_sources"]:
            response = (
                f"{_incomplete_analysis_warning(state['unavailable_sources'])}\n\n"
                f"{response}"
            )
        return {
            "overall_status": "",
            "action_proposed": False,
            "operational_findings": [],
            "priority_items": [],
            "proposed_actions": [],
            "synthesis_briefing": response,
            "analysis_complete": False,
            "synthesis_complete": False,
            "synthesis_run": metadata.model_dump(mode="json"),
            "response_generated": False,
            "final_response": response,
            "errors": [error],
        }

    serialized_findings = [
        finding.model_dump(mode="json") for finding in output.prioritized_findings
    ]
    response = output.briefing
    if state["unavailable_sources"]:
        response = (
            f"{_incomplete_analysis_warning(state['unavailable_sources'])}\n\n"
            f"{response}"
        )
    update: dict[str, Any] = {
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
        "synthesis_briefing": response,
        "synthesis_complete": True,
        "synthesis_run": metadata.model_dump(mode="json"),
        "response_generated": False,
        "final_response": response,
    }
    if metadata.status == SynthesisRunStatus.FALLBACK:
        update["errors"] = [
            WorkflowError(
                stage="synthesis_execution",
                code=metadata.error_code or "llm_synthesis_fallback",
                message=(
                    "LLM synthesis was unavailable; deterministic synthesis "
                    "completed the analysis."
                ),
                component="operations_synthesizer",
                retryable=False,
                details={
                    "mode": metadata.mode,
                    "provider": metadata.provider,
                    "model": metadata.model,
                    "status": metadata.status.value,
                    "fallback_used": True,
                    "exception_type": metadata.error_type,
                },
            )
        ]
    return update


def _create_phase_5_graph_builder(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    runtime_store: SimulatedOperationsStore | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
) -> StateGraph:
    """Build Phase 4 fan-out plus deferred synthesis, without a terminal edge."""

    configured_router = router or RequestRouter()
    configured_synthesizer = synthesis_runner or build_synthesis_runner()
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
            runtime_store=runtime_store,
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
    return graph_builder


def build_phase_5_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    runtime_store: SimulatedOperationsStore | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
    synthesis_runner: SynthesisRunner | None = None,
):
    """Compile Phase 5 and stop immediately after operations synthesis."""

    graph_builder = _create_phase_5_graph_builder(
        router=router,
        reference_date=reference_date,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
        runtime_store=runtime_store,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
    )
    graph_builder.add_edge("operations_synthesizer", END)
    return graph_builder.compile(name="stayops_phase_5_operations_synthesis")
