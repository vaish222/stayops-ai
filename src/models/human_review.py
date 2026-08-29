"""Typed contracts for the checkpointed Phase 7 human-review boundary."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.risk import HumanReviewReason
from src.models.synthesis import PrioritizedFinding, ProposedAction


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HumanReviewRequest(StrictModel):
    request_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    proposed_actions: list[ProposedAction]
    findings: list[PrioritizedFinding]
    review_reasons: list[HumanReviewReason]
    allowed_decisions: list[ReviewDecision] = Field(
        default_factory=lambda: [
            ReviewDecision.APPROVE,
            ReviewDecision.EDIT,
            ReviewDecision.REJECT,
        ]
    )
    edit_requires_reconfirmation: bool = True
    validation_error: str | None = None

    @field_validator("allowed_decisions")
    @classmethod
    def all_decisions_must_be_available(
        cls,
        decisions: list[ReviewDecision],
    ) -> list[ReviewDecision]:
        expected = [
            ReviewDecision.APPROVE,
            ReviewDecision.EDIT,
            ReviewDecision.REJECT,
        ]
        if decisions != expected:
            raise ValueError("human review must offer approve, edit, and reject")
        return decisions


class HumanReviewResponse(StrictModel):
    decision: ReviewDecision
    action_id: str | None = Field(default=None, min_length=1)
    edited_description: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def edit_fields_must_be_consistent(self) -> HumanReviewResponse:
        if self.decision == ReviewDecision.EDIT:
            if self.action_id is None or self.edited_description is None:
                raise ValueError("edit requires action_id and edited_description")
        elif self.edited_description is not None:
            raise ValueError("edited_description is only valid for an edit decision")
        return self


class HumanDecisionRecord(StrictModel):
    decision: ReviewDecision
    action_ids: list[str]
    review_complete: bool
    reviewed_actions: list[ProposedAction]
    edited_description: str | None = None

    @field_validator("action_ids")
    @classmethod
    def action_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("reviewed action IDs must be unique")
        return values

    @model_validator(mode="after")
    def decision_fields_must_be_consistent(self) -> HumanDecisionRecord:
        reviewed_ids = [action.action_id for action in self.reviewed_actions]
        if self.action_ids != reviewed_ids:
            raise ValueError("action_ids must match reviewed_actions")
        if self.decision == ReviewDecision.EDIT:
            if self.review_complete or self.edited_description is None:
                raise ValueError("an edit must remain pending for reconfirmation")
            if len(self.reviewed_actions) != 1:
                raise ValueError("an edit must target exactly one proposed action")
        elif not self.review_complete or self.edited_description is not None:
            raise ValueError("approve and reject decisions must complete review")
        return self
