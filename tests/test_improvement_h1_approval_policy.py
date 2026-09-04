"""H1: recommendations and approval-producing write intent stay separate."""

from datetime import date

from src.graph import build_phase_8_graph, create_initial_state


REFERENCE_DATE = date(2026, 8, 28)


def test_read_only_recommendations_do_not_open_human_approval() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    state = graph.invoke(
        create_initial_state("What needs my attention today?", "h1-read"),
        config={"configurable": {"thread_id": "h1-read"}},
    )

    assert state["proposed_actions"]
    assert state["requires_human_review"] is False
    assert state["review_reasons"] == []
    assert "__interrupt__" not in state
    assert "Waiting for approval" not in state["final_response"]
    assert state["executed_actions"] == []


def test_explicit_write_intent_still_opens_human_approval() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    state = graph.invoke(
        create_initial_state(
            "Send the cleaner at Lake House a message today.",
            "h1-write",
        ),
        config={"configurable": {"thread_id": "h1-write"}},
    )

    assert state["write_requested"] is True
    assert state["requires_human_review"] is True
    assert state["review_reasons"][0]["code"] == "write_requested"
    assert "__interrupt__" in state
    assert state["executed_actions"] == []

