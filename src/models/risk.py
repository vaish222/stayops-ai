"""Typed contracts for the deterministic Phase 6 risk and action gate."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.findings import SpecialistFinding
from src.models.synthesis import PrioritizedFinding, ProposedAction


class ReviewReasonCode(StrEnum):
    SOURCE_DATA_UNAVAILABLE = "source_data_unavailable"
    WRITE_REQUESTED = "write_requested"
    MESSAGE_SEND = "message_send"
    RESERVATION_MODIFICATION = "reservation_modification"
    RECORD_UPDATE = "record_update"
    HIGH_MAINTENANCE_SEVERITY = "high_maintenance_severity"
    LOW_CONFIDENCE = "low_confidence"
    CONFLICTING_FINDINGS = "conflicting_findings"
    GATE_EVALUATION_ERROR = "gate_evaluation_error"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskGateConfig(StrictModel):
    low_confidence_threshold: float = Field(default=0.75, gt=0.0, le=1.0)


class RiskGateInput(StrictModel):
    write_requested: bool = False
    unavailable_sources: list[str] = Field(default_factory=list)
    specialist_findings: list[SpecialistFinding]
    prioritized_findings: list[PrioritizedFinding]
    proposed_actions: list[ProposedAction]

    @field_validator("unavailable_sources")
    @classmethod
    def unavailable_sources_must_be_unique_and_nonblank(
        cls,
        sources: list[str],
    ) -> list[str]:
        if any(not source.strip() for source in sources):
            raise ValueError("unavailable source names must be nonblank")
        if len(sources) != len(set(sources)):
            raise ValueError("unavailable source names must be unique")
        return sources

    @field_validator("specialist_findings")
    @classmethod
    def specialist_ids_must_be_unique(
        cls,
        findings: list[SpecialistFinding],
    ) -> list[SpecialistFinding]:
        ids = [finding.finding_id for finding in findings]
        if len(ids) != len(set(ids)):
            raise ValueError("specialist finding IDs must be unique")
        return findings

    @field_validator("proposed_actions")
    @classmethod
    def action_ids_must_be_unique(
        cls,
        actions: list[ProposedAction],
    ) -> list[ProposedAction]:
        ids = [action.action_id for action in actions]
        if len(ids) != len(set(ids)):
            raise ValueError("proposed action IDs must be unique")
        return actions


class HumanReviewReason(StrictModel):
    code: ReviewReasonCode
    message: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    property_ids: list[str] = Field(default_factory=list)

    @field_validator("source_ids", "property_ids")
    @classmethod
    def values_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("review reason references must be unique")
        return values


class RiskGateOutput(StrictModel):
    requires_human_review: bool
    reasons: list[HumanReviewReason]

    @model_validator(mode="after")
    def review_flag_must_match_reasons(self) -> RiskGateOutput:
        if self.requires_human_review != bool(self.reasons):
            raise ValueError("requires_human_review must match the presence of reasons")
        keys = [
            (reason.code, tuple(reason.source_ids), tuple(reason.property_ids))
            for reason in self.reasons
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("review reasons must be unique")
        return self
