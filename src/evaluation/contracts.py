"""Typed contracts for Phase 10 scenarios, observations, and reports."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents import RequestIntent, RequestRoute
from src.models import (
    FindingCategory,
    OverallStatus,
    ReviewReasonCode,
    SpecialistName,
)
from src.tools import ReadToolName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioCategory(StrEnum):
    ROUTINE_OPERATIONS = "routine_operations"
    SAME_DAY_TURNOVER = "same_day_turnover"
    MISSING_CLEANER_CONFIRMATION = "missing_cleaner_confirmation"
    GUEST_MAINTENANCE_COMPLAINT = "guest_maintenance_complaint"
    CONFLICTING_FINDINGS = "conflicting_findings"
    TOOL_FAILURE = "tool_failure"
    UNAPPROVED_WRITE = "unapproved_write"
    APPROVED_WRITE = "approved_write"


class FailureExpectation(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    RETRY_RECOVERS = "retry_recovers"
    SAFE_ESCALATION = "safe_escalation"


class WriteExpectation(StrEnum):
    NO_WRITE = "no_write"
    PAUSE_WITHOUT_EXECUTION = "pause_without_execution"
    APPROVED_EXECUTION = "approved_execution"
    UNAPPROVED_REJECTION = "unapproved_rejection"


class EvaluationMetric(StrEnum):
    ROUTING_ACCURACY = "routing_accuracy"
    SPECIALIST_ACTIVATION = "specialist_activation"
    PRIORITY_RISK_ACCURACY = "priority_risk_accuracy"
    APPROVAL_ENFORCEMENT = "approval_enforcement"
    SAFE_FAILURE_HANDLING = "safe_failure_handling"
    LATENCY = "latency"
    UNSUPPORTED_CRITICAL_CLAIMS = "unsupported_critical_claims"


class ExpectedRoute(StrictModel):
    intent: RequestIntent
    property_scope: list[str]
    date_scope: str | None
    write_requested: bool

    def as_route(self) -> RequestRoute:
        return RequestRoute.model_validate(self.model_dump())


class EvaluationScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    category: ScenarioCategory
    query: str | None = Field(default=None, min_length=1)
    expected_route: ExpectedRoute | None = None
    expected_specialists: list[SpecialistName] = Field(default_factory=list)
    expected_status: OverallStatus | None = None
    required_categories: list[FindingCategory] = Field(default_factory=list)
    expected_requires_review: bool | None = None
    expected_review_reasons: list[ReviewReasonCode] = Field(default_factory=list)
    failure_plan: dict[ReadToolName, int] = Field(default_factory=dict)
    failure_expectation: FailureExpectation = FailureExpectation.NOT_APPLICABLE
    write_expectation: WriteExpectation = WriteExpectation.NO_WRITE
    inject_conflict: bool = False

    @model_validator(mode="after")
    def scenario_shape_is_consistent(self) -> EvaluationScenario:
        workflow_scenario = self.category != ScenarioCategory.UNAPPROVED_WRITE
        if workflow_scenario and (self.query is None or self.expected_route is None):
            raise ValueError("workflow scenarios require a query and expected route")
        if not workflow_scenario and (self.query is not None or self.expected_route):
            raise ValueError("direct write scenarios cannot include routing inputs")
        if self.failure_plan and self.failure_expectation == FailureExpectation.NOT_APPLICABLE:
            raise ValueError("failure plans require an expected recovery behavior")
        return self


class MetricObservation(StrictModel):
    metric: EvaluationMetric
    applicable: bool
    passed: bool | None
    expected: Any = None
    observed: Any = None
    details: str = Field(min_length=1)

    @model_validator(mode="after")
    def applicability_matches_result(self) -> MetricObservation:
        if self.applicable != (self.passed is not None):
            raise ValueError("applicable metrics must have a pass/fail result")
        return self


class ScenarioResult(StrictModel):
    scenario_id: str
    name: str
    category: ScenarioCategory
    passed: bool
    latency_ms: float = Field(ge=0)
    metrics: list[MetricObservation]
    observations: dict[str, Any]

    @model_validator(mode="after")
    def passed_matches_applicable_metrics(self) -> ScenarioResult:
        expected = all(
            metric.passed for metric in self.metrics if metric.applicable
        )
        if self.passed != expected:
            raise ValueError("scenario pass must match all applicable metrics")
        return self


class ScenarioResults(StrictModel):
    reference_date: date
    generated_at: datetime
    scenarios: list[ScenarioResult]


class AggregateMetric(StrictModel):
    metric: EvaluationMetric
    eligible_scenarios: int = Field(ge=0)
    passed_scenarios: int = Field(ge=0)
    value: float = Field(ge=0)
    unit: Literal["ratio", "count", "milliseconds"]
    comparison: Literal["minimum", "maximum"]
    target: float = Field(ge=0)
    passed: bool


class EvaluationReport(StrictModel):
    reference_date: date
    generated_at: datetime
    scenario_count: int = Field(ge=1)
    passed_scenarios: int = Field(ge=0)
    all_targets_met: bool
    metrics: list[AggregateMetric]
    latency_summary_ms: dict[str, float]
    synthesis_summary: dict[str, Any] = Field(default_factory=dict)
    notes: list[str]
