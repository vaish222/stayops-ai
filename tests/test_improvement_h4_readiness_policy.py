"""H4: readiness requires booking, turnover, and maintenance evidence."""

from datetime import date

from src.graph import build_phase_8_graph, create_initial_state
from src.tools import FailureSimulator, ReadToolName, SimulatedFailureConfig


REFERENCE_DATE = date(2026, 9, 2)


def test_property_readiness_runs_three_required_specialists() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    state = graph.invoke(
        create_initial_state("Is Pine House ready for its next guest?", "h4-ready"),
        config={"configurable": {"thread_id": "h4-ready"}},
    )

    assert state["readiness_detected"] is True
    assert set(state["selected_specialists"]) == {
        "booking",
        "turnover",
        "maintenance",
    }


def test_missing_readiness_source_cannot_produce_an_all_clear() -> None:
    graph = build_phase_8_graph(
        reference_date=REFERENCE_DATE,
        failure_simulator=FailureSimulator(
            SimulatedFailureConfig(
                failures_before_success={ReadToolName.GET_MAINTENANCE_TICKETS: 2}
            )
        ),
    )
    state = graph.invoke(
        create_initial_state("Is Pine House ready for its next guest?", "h4-missing"),
        config={"configurable": {"thread_id": "h4-missing"}},
    )

    assert state["analysis_complete"] is False
    assert state["overall_status"] == "needs_attention"
    assert "incomplete" in state["final_response"].casefold()
    assert " is ready" not in state["final_response"].casefold()
    assert state["requires_human_review"] is False

