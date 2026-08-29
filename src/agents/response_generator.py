"""Deterministic, injectable response generator for terminal workflow state."""

from __future__ import annotations

from langchain_core.runnables import RunnableLambda

from src.models import (
    ResponseGenerationInput,
    ResponseGenerationOutput,
    ReviewDecision,
)


class ResponseGenerator:
    """Render a host response after gating, review, and simulated execution."""

    def __init__(self) -> None:
        self._runnable = RunnableLambda(self._generate)

    def invoke(self, payload: dict) -> ResponseGenerationOutput:
        return self._runnable.invoke(payload)

    @staticmethod
    def _generate(payload: dict) -> ResponseGenerationOutput:
        context = ResponseGenerationInput.model_validate(payload)
        outcome = ResponseGenerator._outcome(context)
        return ResponseGenerationOutput(
            final_response=f"{context.synthesis_briefing}\n\n{outcome}"
        )

    @staticmethod
    def _outcome(context: ResponseGenerationInput) -> str:
        decision = context.human_decision
        if not context.requires_human_review:
            return "No human approval was required and no simulated action was executed."
        if decision is None or not decision.review_complete:
            return "Human review is still pending; no simulated action was executed."
        if decision.decision == ReviewDecision.REJECT:
            return "The proposed action was rejected. No simulated action was executed."
        if context.executed_actions:
            details = ", ".join(
                f"{action.tool_name.value} → {action.target_record_id}"
                for action in context.executed_actions
            )
            count = len(context.executed_actions)
            noun = "action" if count == 1 else "actions"
            outcome = f"Approved: {count} simulated {noun} executed ({details})."
            if context.action_execution_errors:
                failure_count = len(context.action_execution_errors)
                outcome += f" {failure_count} additional action execution failed."
            return outcome
        if context.action_execution_errors:
            return (
                "Approval was recorded, but simulated action execution failed. "
                "Review the workflow error before retrying."
            )
        if context.action_attempts:
            return (
                "Approval was recorded, but the simulated action did not execute. "
                "Review the recorded write attempt before retrying."
            )
        return "The review was approved. No simulated write was required or executed."
