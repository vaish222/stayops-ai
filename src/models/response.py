"""Typed boundary for the final, outcome-aware host response."""

from __future__ import annotations

from typing import Any

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
    host_query: str = ""
    intent: str = ""
    property_scope: list[str] = Field(default_factory=list)
    date_scope: str | None = None
    property_context: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reservation_context: dict[str, dict[str, Any]] = Field(default_factory=dict)
    guest_message_context: dict[str, dict[str, Any]] = Field(default_factory=dict)
    cleaning_context: dict[str, dict[str, Any]] = Field(default_factory=dict)
    maintenance_context: dict[str, dict[str, Any]] = Field(default_factory=dict)
    operational_findings: list[dict[str, Any]] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    analysis_complete: bool = True
    unavailable_sources: list[str] = Field(default_factory=list)


class ResponseGenerationOutput(StrictModel):
    final_response: str = Field(min_length=1)
