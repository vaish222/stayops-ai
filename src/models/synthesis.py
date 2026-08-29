"""Pydantic contracts for evidence-grounded operations synthesis."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    SpecialistFinding,
    SpecialistName,
)


class OverallStatus(StrEnum):
    NEEDS_ATTENTION = "needs_attention"
    WATCH = "watch"
    READY = "ready"
    NO_FINDINGS = "no_findings"


class ActionType(StrEnum):
    REVIEW = "review"
    DRAFT_MESSAGE = "draft_message"
    SEND_MESSAGE = "send_message"
    MODIFY_RESERVATION = "modify_reservation"
    UPDATE_RECORD = "update_record"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperationsSynthesisInput(StrictModel):
    """The synthesizer's entire boundary: structured specialist findings only."""

    specialist_findings: list[SpecialistFinding]

    @field_validator("specialist_findings")
    @classmethod
    def finding_ids_must_be_unique(
        cls,
        findings: list[SpecialistFinding],
    ) -> list[SpecialistFinding]:
        finding_ids = [finding.finding_id for finding in findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("specialist finding IDs must be unique")
        return findings


class PrioritizedFinding(StrictModel):
    priority_rank: int = Field(ge=1)
    property_id: str = Field(pattern=r"^prop_[a-z_]+$")
    severity: FindingSeverity
    summary: str = Field(min_length=1)
    specialist_sources: list[SpecialistName] = Field(min_length=1)
    categories: list[FindingCategory] = Field(min_length=1)
    source_finding_ids: list[str] = Field(min_length=1)
    evidence: list[FindingEvidence] = Field(min_length=1)
    recommended_next_action: str | None
    proposed_action_type: ActionType | None
    requires_attention: bool
    action_proposed: bool
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def proposal_fields_must_be_consistent(self) -> PrioritizedFinding:
        if self.action_proposed != bool(self.recommended_next_action):
            raise ValueError(
                "action_proposed must match the presence of recommended_next_action"
            )
        if self.action_proposed != (self.proposed_action_type is not None):
            raise ValueError(
                "action_proposed must match the presence of proposed_action_type"
            )
        for values, label in (
            (self.specialist_sources, "specialist_sources"),
            (self.categories, "categories"),
            (self.source_finding_ids, "source_finding_ids"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must contain unique values")
        return self


class ProposedAction(StrictModel):
    action_id: str = Field(min_length=1)
    property_id: str = Field(pattern=r"^prop_[a-z_]+$")
    action_type: ActionType
    description: str = Field(min_length=1)
    source_finding_ids: list[str] = Field(min_length=1)
    executed: Literal[False] = False


class OperationsSynthesisOutput(StrictModel):
    overall_status: OverallStatus
    prioritized_findings: list[PrioritizedFinding]
    affected_properties: list[str]
    proposed_actions: list[ProposedAction]
    action_proposed: bool
    briefing: str = Field(min_length=1)

    @model_validator(mode="after")
    def output_fields_must_be_consistent(self) -> OperationsSynthesisOutput:
        expected_ranks = list(range(1, len(self.prioritized_findings) + 1))
        actual_ranks = [finding.priority_rank for finding in self.prioritized_findings]
        if actual_ranks != expected_ranks:
            raise ValueError("priority ranks must be contiguous and ordered")
        expected_properties = sorted(
            {
                finding.property_id
                for finding in self.prioritized_findings
                if finding.requires_attention
            }
        )
        if self.affected_properties != expected_properties:
            raise ValueError("affected_properties must match attention findings")
        if self.action_proposed != bool(self.proposed_actions):
            raise ValueError("action_proposed must match proposed_actions")
        expected_actions = [
            (
                finding.property_id,
                finding.proposed_action_type,
                finding.recommended_next_action,
                finding.source_finding_ids,
            )
            for finding in self.prioritized_findings
            if finding.action_proposed
        ]
        actual_actions = [
            (
                action.property_id,
                action.action_type,
                action.description,
                action.source_finding_ids,
            )
            for action in self.proposed_actions
        ]
        if actual_actions != expected_actions:
            raise ValueError(
                "proposed_actions must trace exactly to prioritized recommendations"
            )
        action_ids = [action.action_id for action in self.proposed_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("proposed action IDs must be unique")
        return self
