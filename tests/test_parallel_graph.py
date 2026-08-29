"""Phase 4 conditional fan-out, safe merge, telemetry, and isolation tests."""

from __future__ import annotations

from datetime import date
from threading import Lock
from time import perf_counter, sleep

import pytest

from src.models import SpecialistName, SpecialistOutput
from src.graph import build_phase_4_graph, create_initial_state, select_specialists
from src.tools import FailureSimulator, ReadToolName, SimulatedFailureConfig


REFERENCE_DATE = date(2026, 8, 28)


def invoke_graph(query: str, **graph_kwargs):
    graph = build_phase_4_graph(reference_date=REFERENCE_DATE, **graph_kwargs)
    return graph.invoke(create_initial_state(query, request_id="phase-4-test"))


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        (
            "daily_briefing",
            {"booking", "guest", "turnover", "maintenance"},
        ),
        ("risk_assessment", {"booking", "guest", "turnover", "maintenance"}),
        ("booking_operations", {"booking", "turnover"}),
        ("turnover_operations", {"booking", "turnover"}),
        ("guest_communications", {"guest"}),
        ("maintenance_operations", {"maintenance"}),
    ],
)
def test_specialist_selection_by_intent(intent: str, expected: set[str]) -> None:
    assert {specialist.value for specialist in select_specialists(intent)} == expected


def test_daily_briefing_runs_four_specialists_and_merges_outputs() -> None:
    result = invoke_graph("What needs my attention today?")

    assert set(result["selected_specialists"]) == {
        "booking",
        "guest",
        "turnover",
        "maintenance",
    }
    runs = {run["agent"]: run for run in result["agent_runs"]}
    assert set(runs) == set(result["selected_specialists"])
    assert all(run["status"] == "succeeded" for run in runs.values())
    assert all(run["latency_ms"] >= 0 for run in runs.values())
    assert len(result["booking_findings"]) > 0
    assert len(result["guest_findings"]) > 0
    assert len(result["turnover_findings"]) > 0
    assert len(result["maintenance_findings"]) > 0
    assert result["operational_findings"] == []
    assert result["priority_items"] == []
    assert result["errors"] == []


def test_guest_query_loads_and_runs_only_guest_context() -> None:
    result = invoke_graph("Are there unresolved guest issues today?")

    assert result["selected_specialists"] == ["guest"]
    assert [run["agent"] for run in result["agent_runs"]] == ["guest"]
    assert result["property_context"]
    assert result["guest_message_context"]
    assert result["reservation_context"] == {}
    assert result["property_rule_context"] == {}
    assert result["cleaning_context"] == {}
    assert result["maintenance_context"] == {}
    assert result["booking_findings"] == []
    assert result["turnover_findings"] == []
    assert result["maintenance_findings"] == []


def test_turnover_query_loads_scoped_booking_and_cleaning_context() -> None:
    result = invoke_graph("Handle the cleaning issue at Lake House today.")

    assert set(result["selected_specialists"]) == {"booking", "turnover"}
    assert set(result["property_context"]) == {"prop_lake_house"}
    assert set(result["reservation_context"]) == {"res_lake_001", "res_lake_002"}
    assert set(result["cleaning_context"]) == {"clean_lake_001"}
    assert set(result["property_rule_context"]) == {"rule_lake_house"}
    assert result["guest_message_context"] == {}
    assert result["maintenance_context"] == {}
    assert result["write_requested"] is True


def test_retryable_context_failure_recovers_before_specialist_runs() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_GUEST_MESSAGES: 1}
        )
    )

    result = invoke_graph(
        "Are there unresolved guest issues today?",
        failure_simulator=simulator,
    )

    assert simulator.attempt_count(ReadToolName.GET_GUEST_MESSAGES) == 2
    assert result["errors"] == []
    assert result["analysis_complete"] is True
    assert result["unavailable_sources"] == []
    assert len(result["guest_findings"]) == 1
    assert result["agent_runs"][0]["warning_count"] == 0


def test_persistent_context_failure_is_isolated_and_reported() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_GUEST_MESSAGES: 2}
        )
    )

    result = invoke_graph(
        "Are there unresolved guest issues today?",
        failure_simulator=simulator,
    )

    assert simulator.attempt_count(ReadToolName.GET_GUEST_MESSAGES) == 2
    assert result["guest_message_context"] == {}
    assert result["guest_findings"] == []
    assert result["analysis_complete"] is False
    assert result["unavailable_sources"] == ["get_guest_messages"]
    assert result["agent_runs"][0]["status"] == "succeeded"
    assert result["agent_runs"][0]["warning_count"] == 1
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["stage"] == "context_loading"
    assert error["tool_name"] == "get_guest_messages"
    assert error["attempts"] == 2


@pytest.mark.parametrize("tool_name", list(ReadToolName))
def test_each_persistent_required_source_marks_analysis_incomplete(
    tool_name: ReadToolName,
) -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(failures_before_success={tool_name: 2})
    )

    result = invoke_graph(
        "What needs my attention today?",
        failure_simulator=simulator,
    )

    assert simulator.attempt_count(tool_name) == 2
    assert result["analysis_complete"] is False
    assert result["unavailable_sources"] == [tool_name.value]
    assert [error["tool_name"] for error in result["errors"]] == [tool_name.value]


class FailingRunner:
    def invoke(self, payload):
        raise RuntimeError("synthetic specialist failure")


def test_one_specialist_exception_does_not_abort_parallel_peers() -> None:
    result = invoke_graph(
        "What needs my attention today?",
        specialist_runners={SpecialistName.GUEST: FailingRunner()},
    )

    runs = {run["agent"]: run for run in result["agent_runs"]}
    assert runs["guest"]["status"] == "failed"
    assert runs["booking"]["status"] == "succeeded"
    assert runs["turnover"]["status"] == "succeeded"
    assert runs["maintenance"]["status"] == "succeeded"
    assert result["guest_findings"] == []
    assert result["booking_findings"]
    assert result["turnover_findings"]
    assert result["maintenance_findings"]
    specialist_errors = [
        error for error in result["errors"] if error["stage"] == "specialist_execution"
    ]
    assert len(specialist_errors) == 1
    assert specialist_errors[0]["component"] == "guest"


class TimedRunner:
    def __init__(
        self,
        specialist: SpecialistName,
        starts: dict[str, float],
        ends: dict[str, float],
        lock: Lock,
    ) -> None:
        self.specialist = specialist
        self.starts = starts
        self.ends = ends
        self.lock = lock

    def invoke(self, payload) -> SpecialistOutput:
        with self.lock:
            self.starts[self.specialist.value] = perf_counter()
        sleep(0.1)
        with self.lock:
            self.ends[self.specialist.value] = perf_counter()
        return SpecialistOutput(
            specialist=self.specialist,
            findings=[],
            analyzed_record_ids=[],
            warnings=[],
        )


def test_broad_query_specialist_branches_execute_concurrently() -> None:
    starts: dict[str, float] = {}
    ends: dict[str, float] = {}
    lock = Lock()
    runners = {
        specialist: TimedRunner(specialist, starts, ends, lock)
        for specialist in SpecialistName
    }

    result = invoke_graph(
        "What needs my attention today?",
        specialist_runners=runners,
    )

    assert set(starts) == {specialist.value for specialist in SpecialistName}
    assert set(ends) == set(starts)
    assert max(starts.values()) < min(ends.values())
    assert all(run["latency_ms"] >= 90 for run in result["agent_runs"])


def test_phase_4_graph_stops_before_synthesis_or_human_review() -> None:
    graph = build_phase_4_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert {
        "request_router",
        "load_context",
        "booking_agent",
        "guest_agent",
        "turnover_agent",
        "maintenance_agent",
    } <= node_names
    assert not {
        "operations_synthesizer",
        "risk_gate",
        "human_review",
        "execute_action",
    } & node_names
