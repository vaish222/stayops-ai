"""Pydantic contracts for evidence-grounded operations synthesis."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    SpecialistFinding,
    SpecialistName,
)
from src.models.operations import MaintenanceStatus
from src.models.write import WriteToolName


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


class SynthesisRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    FALLBACK = "fallback"


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


class SynthesisInvocation(StrictModel):
    """Provider-neutral graph boundary for either synthesis implementation."""

    specialist_findings: list[SpecialistFinding]
    property_scope: list[str] = Field(default_factory=list)
    date_scope: str | None = None
    specialist_errors: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("specialist_findings")
    @classmethod
    def invocation_finding_ids_must_be_unique(
        cls,
        findings: list[SpecialistFinding],
    ) -> list[SpecialistFinding]:
        finding_ids = [finding.finding_id for finding in findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("specialist finding IDs must be unique")
        return findings

    @field_validator("property_scope")
    @classmethod
    def invocation_property_scope_must_be_unique(
        cls,
        property_scope: list[str],
    ) -> list[str]:
        if len(property_scope) != len(set(property_scope)):
            raise ValueError("property_scope cannot contain duplicates")
        return property_scope


class LLMPrioritizedFindingDraft(StrictModel):
    """The only issue-level decisions an LLM is allowed to make."""

    priority_rank: int = Field(ge=1)
    source_finding_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=300)

    @field_validator("source_finding_ids")
    @classmethod
    def draft_source_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source_finding_ids must be unique")
        return values


class LLMSynthesisDraft(StrictModel):
    """Non-executable LLM output; evidence and actions are added deterministically."""

    overall_status: OverallStatus
    prioritized_findings: list[LLMPrioritizedFindingDraft]

    @model_validator(mode="after")
    def draft_ranks_must_be_contiguous(self) -> LLMSynthesisDraft:
        expected = list(range(1, len(self.prioritized_findings) + 1))
        actual = [finding.priority_rank for finding in self.prioritized_findings]
        if actual != expected:
            raise ValueError("LLM priority ranks must be contiguous and ordered")
        return self


class SynthesisRunMetadata(StrictModel):
    mode: Literal["deterministic", "llm"]
    provider: Literal["nebius", "ollama"] | None = None
    model: str | None = None
    status: SynthesisRunStatus
    latency_ms: float = Field(ge=0)
    prioritized_finding_count: int = Field(ge=0)
    fallback_used: bool = False
    error_code: str | None = None
    error_type: str | None = None

    @model_validator(mode="after")
    def metadata_fields_must_be_consistent(self) -> SynthesisRunMetadata:
        if self.mode == "deterministic" and (
            self.provider is not None or self.model is not None
        ):
            raise ValueError("deterministic synthesis cannot include provider metadata")
        if self.mode == "llm" and (self.provider is None or self.model is None):
            raise ValueError("LLM synthesis requires provider and model metadata")
        if self.fallback_used != (self.status == SynthesisRunStatus.FALLBACK):
            raise ValueError("fallback_used must match fallback status")
        if self.status == SynthesisRunStatus.COMPLETED and self.error_code is not None:
            raise ValueError("completed synthesis cannot include an error code")
        return self


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
    tool_name: WriteToolName | None = None
    target_record_id: str | None = Field(default=None, min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    executed: Literal[False] = False

    @model_validator(mode="after")
    def executable_fields_must_be_consistent(self) -> ProposedAction:
        expected_action_types = {
            WriteToolName.SEND_GUEST_MESSAGE: ActionType.SEND_MESSAGE,
            WriteToolName.SEND_CLEANER_MESSAGE: ActionType.SEND_MESSAGE,
            WriteToolName.UPDATE_MAINTENANCE_STATUS: ActionType.UPDATE_RECORD,
        }
        if self.tool_name is None:
            if self.target_record_id is not None or self.parameters:
                raise ValueError("non-executable actions cannot include tool fields")
            if self.action_type in {ActionType.SEND_MESSAGE, ActionType.UPDATE_RECORD}:
                raise ValueError("write actions must specify an executable tool")
            return self
        if self.target_record_id is None:
            raise ValueError("executable actions must specify target_record_id")
        if self.action_type != expected_action_types[self.tool_name]:
            raise ValueError("action_type does not match the selected write tool")
        if self.tool_name in {
            WriteToolName.SEND_GUEST_MESSAGE,
            WriteToolName.SEND_CLEANER_MESSAGE,
        }:
            if self.parameters != {"message": self.description}:
                raise ValueError("message tools must execute the reviewed description")
        else:
            if set(self.parameters) != {"status"}:
                raise ValueError("maintenance updates require exactly one status")
            try:
                MaintenanceStatus(self.parameters["status"])
            except ValueError as exc:
                raise ValueError("maintenance update status is invalid") from exc
        return self


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


class SynthesisExecutionResult(StrictModel):
    """Synthesis output plus safe, non-secret execution metadata."""

    output: OperationsSynthesisOutput
    metadata: SynthesisRunMetadata
