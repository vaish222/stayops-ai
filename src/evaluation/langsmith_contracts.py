"""Typed contracts for the Week 4 single-case LangSmith baseline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LangSmithExpectedBehavior(StrictModel):
    intent: str = Field(min_length=1)
    date_expression: str = Field(min_length=1)
    resolved_date_scope: str = Field(min_length=1)
    property_scope: Literal["all"]
    property_ids: list[str]
    specialists: list[str]
    human_review: bool


class LangSmithEvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^STAY-\d{3}$")
    query: str = Field(min_length=1)
    scenario_type: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    run_version: str = Field(min_length=1)
    reference_date: date
    expected: LangSmithExpectedBehavior


class LangSmithActualBehavior(StrictModel):
    predicted_intent: str
    resolved_property_ids: list[str]
    resolved_date_scope: str | None
    activated_specialists: list[str]
    tools_called: list[str]
    tool_attempts: list[dict[str, Any]]
    human_review_triggered: bool
    workflow_errors: list[dict[str, Any]]
    synthesizer_mode: str | None
    model_provider: str | None
    model: str | None
    response_generated: bool
    outcome: Literal["completed", "interrupted"]
    end_to_end_latency_ms: float = Field(ge=0)


class LangSmithBaselineResult(StrictModel):
    case_id: str
    generated_at: datetime
    tracing_enabled: bool
    project: str
    run_id: UUID
    trace_id: UUID
    expected: LangSmithExpectedBehavior
    actual: LangSmithActualBehavior
    comparisons: dict[str, bool]
    all_expectations_met: bool
