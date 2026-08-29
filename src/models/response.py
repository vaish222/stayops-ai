"""Typed boundary for the final, outcome-aware host response."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.models.human_review import HumanDecisionRecord
from src.models.write import ExecutedAction, WriteAttempt


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseGenerationInput(StrictModel):
    """Only information needed to explain the completed workflow outcome."""

    synthesis_briefing: str = Field(min_length=1)
    requires_human_review: bool
    human_decision: HumanDecisionRecord | None
    action_attempts: list[WriteAttempt]
    executed_actions: list[ExecutedAction]
    action_execution_errors: list[str] = Field(default_factory=list)


class ResponseGenerationOutput(StrictModel):
    final_response: str = Field(min_length=1)
