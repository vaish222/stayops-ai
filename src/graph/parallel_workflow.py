"""Phase 4 LangGraph workflow with isolated context loading and parallel agents."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

from src.agents import (
    BookingAgent,
    GuestAgent,
    MaintenanceAgent,
    RequestIntent,
    RequestRouter,
    TurnoverAgent,
)
from src.models import SpecialistName, SpecialistOutput
from src.graph.routing import request_router_node
from src.graph.state import AgentRunLog, StayOpsState, WorkflowError
from src.tools import (
    FailureSimulator,
    ReadResult,
    ReadToolName,
    get_cleaning_schedule,
    get_guest_messages,
    get_maintenance_tickets,
    get_properties,
    get_property_rules,
    get_reservations,
)
from src.tools.read_tools import DEFAULT_DATA_DIR


class SpecialistRunner(Protocol):
    def invoke(self, payload: dict[str, Any]) -> SpecialistOutput: ...


SPECIALIST_NODE_NAMES = {
    SpecialistName.BOOKING: "booking_agent",
    SpecialistName.GUEST: "guest_agent",
    SpecialistName.TURNOVER: "turnover_agent",
    SpecialistName.MAINTENANCE: "maintenance_agent",
}

SPECIALIST_FINDING_FIELDS = {
    SpecialistName.BOOKING: "booking_findings",
    SpecialistName.GUEST: "guest_findings",
    SpecialistName.TURNOVER: "turnover_findings",
    SpecialistName.MAINTENANCE: "maintenance_findings",
}

SPECIALIST_SOURCE_TOOLS = {
    SpecialistName.BOOKING: {ReadToolName.GET_RESERVATIONS},
    SpecialistName.GUEST: {ReadToolName.GET_GUEST_MESSAGES},
    SpecialistName.TURNOVER: {
        ReadToolName.GET_RESERVATIONS,
        ReadToolName.GET_CLEANING_SCHEDULE,
        ReadToolName.GET_PROPERTY_RULES,
    },
    SpecialistName.MAINTENANCE: {
        ReadToolName.GET_RESERVATIONS,
        ReadToolName.GET_MAINTENANCE_TICKETS,
    },
}

ALL_SPECIALISTS = [
    SpecialistName.BOOKING,
    SpecialistName.GUEST,
    SpecialistName.TURNOVER,
    SpecialistName.MAINTENANCE,
]


def select_specialists(intent: str) -> list[SpecialistName]:
    """Select the smallest useful specialist set for a routed intent."""

    if intent in {
        RequestIntent.DAILY_BRIEFING.value,
        RequestIntent.RISK_ASSESSMENT.value,
        RequestIntent.GENERAL_OPERATIONS.value,
    }:
        return list(ALL_SPECIALISTS)
    if intent == RequestIntent.BOOKING_OPERATIONS.value:
        return [SpecialistName.BOOKING, SpecialistName.TURNOVER]
    if intent == RequestIntent.TURNOVER_OPERATIONS.value:
        return [SpecialistName.BOOKING, SpecialistName.TURNOVER]
    if intent == RequestIntent.GUEST_COMMUNICATIONS.value:
        return [SpecialistName.GUEST]
    if intent == RequestIntent.MAINTENANCE_OPERATIONS.value:
        return [SpecialistName.MAINTENANCE]
    return list(ALL_SPECIALISTS)


def _date_bounds(date_scope: str | None) -> tuple[date | None, date | None]:
    if date_scope is None:
        return None, None
    values = [date.fromisoformat(value) for value in date_scope.split("/")]
    return (values[0], values[0]) if len(values) == 1 else (values[0], values[1])


def _run_read_with_retry(
    tool_name: ReadToolName,
    call: Callable[[], ReadResult[Any]],
) -> tuple[ReadResult[Any] | None, int, WorkflowError | None]:
    attempts = 0
    while attempts < 2:
        attempts += 1
        try:
            result = call()
        except Exception as exc:  # Defensive boundary around each independent source.
            return None, attempts, WorkflowError(
                stage="context_loading",
                code="unexpected_tool_exception",
                message=f"{tool_name.value} raised an unexpected exception.",
                component=tool_name.value,
                tool_name=tool_name.value,
                retryable=False,
                attempts=attempts,
                details={"exception_type": type(exc).__name__, "reason": str(exc)},
            )

        if result.success:
            return result, attempts, None
        if result.error is None:
            return None, attempts, WorkflowError(
                stage="context_loading",
                code="invalid_tool_result",
                message=f"{tool_name.value} failed without a structured error.",
                component=tool_name.value,
                tool_name=tool_name.value,
                retryable=False,
                attempts=attempts,
            )
        if not result.error.retryable or attempts == 2:
            return result, attempts, WorkflowError(
                stage="context_loading",
                code=result.error.code.value,
                message=result.error.message,
                component=tool_name.value,
                tool_name=tool_name.value,
                retryable=result.error.retryable,
                attempts=attempts,
                details=result.error.details,
            )
    raise AssertionError("unreachable retry loop")


def load_context_node(
    state: StayOpsState,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> dict[str, Any]:
    """Load needed sources independently; retry retryable failures once."""

    selected = select_specialists(state["intent"])
    needed_tools = {ReadToolName.GET_PROPERTIES}
    for specialist in selected:
        needed_tools.update(SPECIALIST_SOURCE_TOOLS[specialist])

    property_ids = state["property_scope"] or None
    start_date, end_date = _date_bounds(state["date_scope"])
    calls: dict[ReadToolName, Callable[[], ReadResult[Any]]] = {
        ReadToolName.GET_PROPERTIES: lambda: get_properties(
            property_ids,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
        ReadToolName.GET_PROPERTY_RULES: lambda: get_property_rules(
            property_ids,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
        ReadToolName.GET_RESERVATIONS: lambda: get_reservations(
            property_ids,
            start_date,
            end_date,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
        ReadToolName.GET_GUEST_MESSAGES: lambda: get_guest_messages(
            property_ids,
            start_date,
            end_date,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
        ReadToolName.GET_CLEANING_SCHEDULE: lambda: get_cleaning_schedule(
            property_ids,
            start_date,
            end_date,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
        ReadToolName.GET_MAINTENANCE_TICKETS: lambda: get_maintenance_tickets(
            property_ids,
            start_date,
            end_date,
            data_dir=data_dir,
            failure_simulator=failure_simulator,
        ),
    }

    records_by_tool: dict[ReadToolName, list[Any]] = {
        tool_name: [] for tool_name in ReadToolName
    }
    errors: list[WorkflowError] = []
    for tool_name in ReadToolName:
        if tool_name not in needed_tools:
            continue
        result, _, error = _run_read_with_retry(tool_name, calls[tool_name])
        if result is not None and result.success:
            records_by_tool[tool_name] = result.items
        if error is not None:
            errors.append(error)

    def serialized_index(tool_name: ReadToolName) -> dict[str, dict[str, Any]]:
        return {
            item.id: item.model_dump(mode="json")
            for item in records_by_tool[tool_name]
        }

    unavailable_sources = list(
        dict.fromkeys(
            error["tool_name"]
            for error in errors
            if error.get("tool_name")
        )
    )

    return {
        "selected_specialists": [specialist.value for specialist in selected],
        "property_context": serialized_index(ReadToolName.GET_PROPERTIES),
        "property_rule_context": serialized_index(ReadToolName.GET_PROPERTY_RULES),
        "reservation_context": serialized_index(ReadToolName.GET_RESERVATIONS),
        "guest_message_context": serialized_index(ReadToolName.GET_GUEST_MESSAGES),
        "cleaning_context": serialized_index(ReadToolName.GET_CLEANING_SCHEDULE),
        "maintenance_context": serialized_index(ReadToolName.GET_MAINTENANCE_TICKETS),
        "analysis_complete": not unavailable_sources,
        "unavailable_sources": unavailable_sources,
        "errors": errors,
    }


def _context_errors_for(
    state: StayOpsState,
    tool_names: set[ReadToolName],
) -> list[WorkflowError]:
    expected_names = {tool_name.value for tool_name in tool_names}
    return [
        error
        for error in state["errors"]
        if error.get("stage") == "context_loading"
        and error.get("tool_name") in expected_names
    ]


def _specialist_payload(
    state: StayOpsState,
    specialist: SpecialistName,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "property_scope": state["property_scope"],
        "date_scope": state["date_scope"],
        "source_errors": _context_errors_for(
            state,
            SPECIALIST_SOURCE_TOOLS[specialist],
        ),
    }
    if specialist in {
        SpecialistName.BOOKING,
        SpecialistName.TURNOVER,
        SpecialistName.MAINTENANCE,
    }:
        payload["reservations"] = list(state["reservation_context"].values())
    if specialist == SpecialistName.GUEST:
        payload["guest_messages"] = list(state["guest_message_context"].values())
    if specialist == SpecialistName.TURNOVER:
        payload["cleaning_schedule"] = list(state["cleaning_context"].values())
        payload["property_rules"] = list(state["property_rule_context"].values())
    if specialist == SpecialistName.MAINTENANCE:
        payload["maintenance_tickets"] = list(state["maintenance_context"].values())
    return payload


def _run_specialist_node(
    state: StayOpsState,
    *,
    specialist: SpecialistName,
    runner: SpecialistRunner,
) -> dict[str, Any]:
    started_at = perf_counter_ns()
    finding_field = SPECIALIST_FINDING_FIELDS[specialist]
    try:
        output = runner.invoke(_specialist_payload(state, specialist))
        latency_ms = round((perf_counter_ns() - started_at) / 1_000_000, 3)
        run_log = AgentRunLog(
            agent=specialist.value,
            status="succeeded",
            latency_ms=latency_ms,
            finding_count=len(output.findings),
            warning_count=len(output.warnings),
            analyzed_record_count=len(output.analyzed_record_ids),
            error=None,
        )
        return {
            finding_field: [finding.model_dump(mode="json") for finding in output.findings],
            "agent_runs": [run_log],
        }
    except Exception as exc:  # One failing parallel branch must not abort its peers.
        latency_ms = round((perf_counter_ns() - started_at) / 1_000_000, 3)
        message = f"{specialist.value} specialist failed: {type(exc).__name__}: {exc}"
        run_log = AgentRunLog(
            agent=specialist.value,
            status="failed",
            latency_ms=latency_ms,
            finding_count=0,
            warning_count=0,
            analyzed_record_count=0,
            error=message,
        )
        error = WorkflowError(
            stage="specialist_execution",
            code="specialist_failure",
            message=message,
            component=specialist.value,
            retryable=False,
            details={"exception_type": type(exc).__name__},
        )
        return {
            finding_field: [],
            "agent_runs": [run_log],
            "errors": [error],
        }


def build_phase_4_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
    specialist_runners: dict[SpecialistName, SpecialistRunner] | None = None,
):
    """Compile route -> context -> conditional parallel specialists -> END."""

    configured_router = router or RequestRouter()
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

    graph_builder.add_edge(START, "request_router")
    graph_builder.add_edge("request_router", "load_context")
    graph_builder.add_conditional_edges(
        "load_context",
        route_to_specialists,
        list(SPECIALIST_NODE_NAMES.values()),
    )
    for node_name in SPECIALIST_NODE_NAMES.values():
        graph_builder.add_edge(node_name, END)
    return graph_builder.compile(name="stayops_phase_4_parallel_specialists")
