"""Tests for the post-decision response-generation boundary."""

from __future__ import annotations

from datetime import date

from src.agents import ResponseGenerator
from src.agents.response_generator import format_stayops_response
from src.graph import (
    build_phase_8_graph,
    create_initial_state,
    response_generator_node,
)


REFERENCE_DATE = date(2026, 8, 28)


def answer_for(query: str) -> tuple[dict, str]:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    thread_id = f"response-intent-{abs(hash(query))}"
    state = graph.invoke(
        create_initial_state(query, request_id=thread_id),
        config={"configurable": {"thread_id": thread_id}},
    )
    return state, format_stayops_response(state)


def assert_user_facing(answer: str) -> None:
    forbidden = (
        "overall status",
        "prioritized items",
        "affected properties",
        "analysis complete",
        "response_generator",
        "load_context",
    )
    assert not any(term in answer.casefold() for term in forbidden)


def test_response_generator_reports_safe_terminal_outcome() -> None:
    output = ResponseGenerator().invoke(
        {
            "synthesis_briefing": "All scoped operations are ready.",
            "requires_human_review": False,
            "human_decision": None,
            "action_attempts": [],
            "executed_actions": [],
        }
    )

    assert output.final_response.startswith("All scoped operations are ready.")
    assert "No approval was required" in output.final_response


def test_response_generator_reports_approved_execution_failure() -> None:
    output = ResponseGenerator().invoke(
        {
            "synthesis_briefing": "One action needs attention.",
            "requires_human_review": True,
            "human_decision": {
                "decision": "approve",
                "action_ids": [],
                "review_complete": True,
                "reviewed_actions": [],
            },
            "action_attempts": [],
            "executed_actions": [],
            "action_execution_errors": ["Synthetic write failure."],
        }
    )

    assert "could not be completed" in output.final_response


class FailingResponseRunner:
    def invoke(self, payload):
        raise RuntimeError("synthetic response failure")


def test_response_node_preserves_briefing_when_generation_fails() -> None:
    state = create_initial_state("What is happening?", request_id="response-test")
    state["synthesis_briefing"] = "Grounded operations briefing."

    update = response_generator_node(state, generator=FailingResponseRunner())

    assert update["response_generated"] is False
    assert update["final_response"].startswith("StayOps could not prepare an answer")
    assert update["errors"][0]["stage"] == "response_generation"


def test_arrivals_answer_leads_with_count_and_arrival_details() -> None:
    state, answer = answer_for("Which guests are arriving today?")

    assert state["intent"] == "booking_operations"
    assert answer.splitlines()[0] == "3 arrivals are scheduled on Aug 28."
    assert "**Lake House** — Jordan Vale, 4:00 PM, 6 guests" in answer
    assert "**City Loft** — Taylor Moon, 3:00 PM, 2 guests" in answer
    assert "**Beach Bungalow** — Quinn Shell, 3:00 PM, 4 guests" in answer
    assert_user_facing(answer)


def test_daily_attention_answer_lists_needs_action_before_watch_items() -> None:
    state, answer = answer_for("What needs my attention today?")

    assert state["intent"] == "daily_briefing"
    assert answer.splitlines()[0] == "3 Needs Action items require attention on Aug 28."
    assert "**Lake House**" in answer
    assert "**Why it matters:**" in answer
    assert "**Next:**" in answer
    assert "### Heads up" in answer
    assert "3 Watch items:" in answer
    assert answer.index("**Lake House**") < answer.index("### Heads up")
    assert_user_facing(answer)


def test_turnover_answer_leads_with_timing_and_confirmation_risk() -> None:
    state, answer = answer_for("What cleaning risks need attention today?")

    assert state["intent"] == "turnover_operations"
    assert answer.splitlines()[0] == (
        "1 property has a cleaning or turnover risk on Aug 28."
    )
    assert "Checkout 11:00 AM" in answer
    assert "cleaning target 2:00 PM" in answer
    assert "next check-in 4:00 PM" in answer
    assert "confirmation pending" in answer
    assert "Waiting for approval:" not in answer
    assert_user_facing(answer)


def test_guest_message_answer_names_waiting_guest_and_exact_approval() -> None:
    state, answer = answer_for("Which guest messages need a reply today?")

    assert state["intent"] == "guest_communications"
    assert answer.splitlines()[0] == "1 guest is waiting for a reply on Aug 28."
    assert "**Morgan Frost · Pine House**" in answer
    assert "High urgency" in answer
    assert "air conditioner stopped cooling" in answer
    assert "No reply is waiting for approval." in answer
    assert_user_facing(answer)


def test_maintenance_answer_leads_with_affected_properties_and_details() -> None:
    state, answer = answer_for("What maintenance needs attention today?")

    assert state["intent"] == "maintenance_operations"
    assert answer.splitlines()[0] == (
        "2 properties have active maintenance issues on Aug 28."
    )
    assert "Air conditioner is not cooling" in answer
    assert "High severity" in answer
    assert "guest impact: Yes" in answer
    assert "status: Open" in answer
    assert "**Next:**" in answer
    assert_user_facing(answer)


def test_property_status_answer_directly_states_readiness() -> None:
    state, answer = answer_for("What is the status of Lake House today?")

    assert state["intent"] == "daily_briefing"
    assert answer.splitlines()[0].startswith("Lake House needs action because")
    assert "missing cleaner confirmation" in answer
    assert "**Why:**" in answer
    assert "**Next:**" in answer
    assert_user_facing(answer)


def test_guest_message_answer_is_clear_when_no_reply_matches() -> None:
    _, answer = answer_for("Which guest messages need a reply tomorrow?")

    assert answer.splitlines()[0] == "No guests are waiting for a reply on Aug 29."
    assert_user_facing(answer)
