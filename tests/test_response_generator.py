"""Tests for the post-decision response-generation boundary."""

from __future__ import annotations

from src.agents import ResponseGenerator
from src.graph import create_initial_state, response_generator_node


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
    assert "No human approval was required" in output.final_response


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

    assert "execution failed" in output.final_response


class FailingResponseRunner:
    def invoke(self, payload):
        raise RuntimeError("synthetic response failure")


def test_response_node_preserves_briefing_when_generation_fails() -> None:
    state = create_initial_state("What is happening?", request_id="response-test")
    state["synthesis_briefing"] = "Grounded operations briefing."

    update = response_generator_node(state, generator=FailingResponseRunner())

    assert update["response_generated"] is False
    assert update["final_response"].startswith("Grounded operations briefing.")
    assert update["errors"][0]["stage"] == "response_generation"
