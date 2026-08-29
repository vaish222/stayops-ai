"""Post-decision response generation for the complete StayOps workflow."""

from __future__ import annotations

from typing import Any, Protocol

from src.agents import ResponseGenerator
from src.graph.state import StayOpsState, WorkflowError
from src.models import ResponseGenerationOutput


class ResponseRunner(Protocol):
    def invoke(self, payload: dict[str, Any]) -> ResponseGenerationOutput: ...


def response_generator_node(
    state: StayOpsState,
    *,
    generator: ResponseRunner | None = None,
) -> dict[str, Any]:
    """Generate the narrative only after the workflow outcome is known."""

    runner = generator or ResponseGenerator()
    payload = {
        "synthesis_briefing": state["synthesis_briefing"],
        "requires_human_review": state["requires_human_review"],
        "human_decision": state["human_decision"],
        "action_attempts": state["action_attempts"],
        "executed_actions": state["executed_actions"],
        "action_execution_errors": [
            error["message"]
            for error in state["errors"]
            if error.get("stage") == "action_execution"
        ],
        "host_query": state["host_query"],
        "intent": state["intent"],
        "property_scope": state["property_scope"],
        "date_scope": state["date_scope"],
        "property_context": state["property_context"],
        "reservation_context": state["reservation_context"],
        "guest_message_context": state["guest_message_context"],
        "cleaning_context": state["cleaning_context"],
        "maintenance_context": state["maintenance_context"],
        "operational_findings": state["operational_findings"],
        "proposed_actions": state["proposed_actions"],
        "analysis_complete": state["analysis_complete"],
        "unavailable_sources": state["unavailable_sources"],
    }
    try:
        output = runner.invoke(payload)
    except Exception as exc:
        error = WorkflowError(
            stage="response_generation",
            code="response_generation_failure",
            message=f"Final response generation failed: {type(exc).__name__}: {exc}",
            component="response_generator",
            retryable=False,
            details={"exception_type": type(exc).__name__},
        )
        return {
            "final_response": (
                "StayOps could not prepare an answer for this request. "
                "Review the operational details before taking action."
            ),
            "response_generated": False,
            "errors": [error],
        }
    return {
        "final_response": output.final_response,
        "response_generated": True,
    }
