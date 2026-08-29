"""Typed contracts for Phase 8 approval-protected simulated writes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WriteToolName(StrEnum):
    SEND_GUEST_MESSAGE = "send_guest_message"
    SEND_CLEANER_MESSAGE = "send_cleaner_message"
    UPDATE_MAINTENANCE_STATUS = "update_maintenance_status"


class WriteErrorCode(StrEnum):
    APPROVAL_REQUIRED = "approval_required"
    INVALID_APPROVAL_TOKEN = "invalid_approval_token"
    ACTION_MISMATCH = "action_mismatch"
    TOKEN_ALREADY_USED = "token_already_used"
    TOOL_MISMATCH = "tool_mismatch"


class WriteAttemptStatus(StrEnum):
    REJECTED = "rejected"
    EXECUTED = "executed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalGrant(StrictModel):
    token: str = Field(pattern=r"^apt_[A-Za-z0-9_-]{32,}$")
    request_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    tool_name: WriteToolName
    action_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class WriteAttempt(StrictModel):
    attempt_id: str = Field(min_length=1)
    tool_name: WriteToolName
    action_id: str = Field(min_length=1)
    property_id: str = Field(pattern=r"^prop_[a-z_]+$")
    target_record_id: str = Field(min_length=1)
    approved: bool
    status: WriteAttemptStatus
    error_code: WriteErrorCode | None = None
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def result_fields_must_be_consistent(self) -> WriteAttempt:
        if self.status == WriteAttemptStatus.EXECUTED:
            if not self.approved or self.error_code is not None:
                raise ValueError("executed attempts must be approved without an error")
        elif self.approved or self.error_code is None:
            raise ValueError("rejected attempts must include an authorization error")
        return self


class ExecutedAction(StrictModel):
    execution_id: str = Field(min_length=1)
    tool_name: WriteToolName
    action_id: str = Field(min_length=1)
    property_id: str = Field(pattern=r"^prop_[a-z_]+$")
    target_record_id: str = Field(min_length=1)
    simulated: Literal[True] = True
    result: dict[str, Any]


class WriteResult(StrictModel):
    success: bool
    attempt: WriteAttempt
    execution: ExecutedAction | None = None

    @model_validator(mode="after")
    def result_must_match_attempt(self) -> WriteResult:
        if self.success != (self.attempt.status == WriteAttemptStatus.EXECUTED):
            raise ValueError("success must match the write attempt status")
        if self.success != (self.execution is not None):
            raise ValueError("successful writes must include one execution record")
        if self.execution is not None:
            if (
                self.execution.action_id != self.attempt.action_id
                or self.execution.tool_name != self.attempt.tool_name
            ):
                raise ValueError("execution must match its write attempt")
        return self
