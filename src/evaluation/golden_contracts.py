"""Strict contracts for the frozen Week 4 golden-dataset baseline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agents import RequestIntent
from src.models import OverallStatus, SpecialistName
from src.tools import ReadToolName


FROZEN_DATASET_SHA256 = (
    "b12b4e0460c521a021293178ec5414ccf6567c3778270f414d56431987ab5a97"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenInput(StrictModel):
    query: str = Field(min_length=1)


class GoldenExpected(StrictModel):
    intent: RequestIntent
    property_ids: list[str]
    date_start: date | None
    date_end: date | None
    required_specialists: list[SpecialistName]
    allowed_specialists: list[SpecialistName]
    required_tools: list[ReadToolName]
    allowed_tools: list[ReadToolName]
    minimum_required_facts: list[dict[str, Any]]
    forbidden_claims: list[str]
    overall_status: OverallStatus | None
    human_review_required: bool
    write_intent: bool
    write_execution_expected: bool
    failure_behavior: dict[str, Any] | None

    @field_validator(
        "property_ids",
        "required_specialists",
        "allowed_specialists",
        "required_tools",
        "allowed_tools",
    )
    @classmethod
    def lists_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("expected lists cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def expected_values_are_consistent(self) -> GoldenExpected:
        if (self.date_start is None) != (self.date_end is None):
            raise ValueError("date_start and date_end must both be set or both be null")
        if self.date_start and self.date_end and self.date_start > self.date_end:
            raise ValueError("date range cannot be reversed")
        if not set(self.required_specialists) <= set(self.allowed_specialists):
            raise ValueError("required specialists must be allowed")
        if not set(self.required_tools) <= set(self.allowed_tools):
            raise ValueError("required tools must be allowed")
        return self

    @property
    def date_scope(self) -> str | None:
        if self.date_start is None:
            return None
        if self.date_start == self.date_end:
            return self.date_start.isoformat()
        assert self.date_end is not None
        return f"{self.date_start.isoformat()}/{self.date_end.isoformat()}"


class FailureInjection(StrictModel):
    type: Literal["read_tool", "llm_synthesizer"]
    tool: ReadToolName | None = None
    failures_before_success: int | None = Field(default=None, ge=0)
    mode: Literal["invalid_structured_output"] | None = None

    @model_validator(mode="after")
    def shape_matches_type(self) -> FailureInjection:
        if self.type == "read_tool":
            if self.tool is None or self.failures_before_success is None:
                raise ValueError("read_tool injection requires tool and failure count")
            if self.mode is not None:
                raise ValueError("read_tool injection cannot include mode")
        else:
            if self.mode != "invalid_structured_output":
                raise ValueError("LLM injection requires invalid_structured_output mode")
            if self.tool is not None or self.failures_before_success is not None:
                raise ValueError("LLM injection cannot include read-tool fields")
        return self


class GoldenCase(StrictModel):
    case_id: str = Field(pattern=r"^STAY-\d{3}$")
    dataset_version: Literal["v1"]
    scenario_type: Literal["happy_path", "edge", "failure", "adversarial"]
    difficulty: Literal["easy", "medium", "hard"]
    domain: str = Field(min_length=1)
    reference_date: date
    input: GoldenInput
    expected: GoldenExpected
    failure_injection: FailureInjection | None
    evaluation_tags: list[str]
    label_notes: str


class SourceOfTruth(StrictModel):
    repository: str
    branch: str
    fixtures: list[str]
    labeling_principle: str


class ScenarioDistribution(StrictModel):
    happy_path: int
    edge: int
    failure: int
    adversarial: int
    total: int


class GoldenDataset(StrictModel):
    dataset_name: str
    dataset_version: Literal["v1"]
    reference_date_default: date
    source_of_truth: SourceOfTruth
    scenario_distribution: ScenarioDistribution
    cases: list[GoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def dataset_is_complete_and_consistent(self) -> GoldenDataset:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        expected_ids = [f"STAY-{index:03d}" for index in range(1, 51)]
        if ids != expected_ids:
            raise ValueError("golden_dataset_v1 must contain ordered STAY-001..STAY-050")
        observed = {
            kind: sum(case.scenario_type == kind for case in self.cases)
            for kind in ("happy_path", "edge", "failure", "adversarial")
        }
        declared = self.scenario_distribution.model_dump(exclude={"total"})
        if observed != declared or self.scenario_distribution.total != len(self.cases):
            raise ValueError("declared scenario distribution does not match cases")
        return self


class FactMatch(StrictModel):
    expected: dict[str, Any]
    matched: bool
    evidence_source: str | None = None
    actual_match: dict[str, Any] | None = None


class ComponentScore(StrictModel):
    applicable: bool
    score: float | None = Field(default=None, ge=0, le=1)
    passed: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def applicability_matches_values(self) -> ComponentScore:
        if self.applicable != (self.score is not None and self.passed is not None):
            raise ValueError("applicable scores require score and pass values")
        return self


class GoldenActual(StrictModel):
    actual_intent: str
    actual_property_ids: list[str]
    actual_date_scope: str | None
    actual_write_requested: bool
    selected_specialists: list[str]
    specialists_actually_run: list[str]
    tools_called: list[str]
    tool_attempt_counts: dict[str, int]
    unavailable_sources: list[str]
    analysis_complete: bool
    synthesis_complete: bool
    risk_gate_evaluated: bool
    response_generated: bool
    workflow_errors: list[dict[str, Any]]
    agent_runs: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    human_review_triggered: bool
    write_tools_called: list[str]
    write_executed: bool
    final_response: str | None
    overall_status: str | None
    structured_findings: list[dict[str, Any]]
    specialist_findings: dict[str, list[dict[str, Any]]]
    end_to_end_latency_ms: float = Field(ge=0)
    llm_token_usage: dict[str, int] | None
    synthesizer_mode: str | None
    model_provider: str | None
    model: str | None
    langsmith_trace_id: UUID
    langsmith_run_id: UUID
    langsmith_run_url: str | None = None
    interrupted_for_review: bool


class GoldenCaseResult(StrictModel):
    case_id: str
    dataset_version: str
    run_version: str
    scenario_type: str
    difficulty: str
    domain: str
    reference_date: date
    query: str
    expected: GoldenExpected
    actual: GoldenActual
    fact_matches: list[FactMatch]
    scores: dict[str, ComponentScore]
    forbidden_claim_violations: list[dict[str, Any]]
    needs_human_or_llm_review: bool
    case_pass: bool


class GoldenRunResults(StrictModel):
    dataset_version: str
    run_version: str
    synthesizer_mode: str
    dataset_sha256: str
    generated_at: datetime
    cases: list[GoldenCaseResult]
