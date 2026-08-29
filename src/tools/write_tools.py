"""Approval-protected simulated write tools for Phase 8."""

from __future__ import annotations

import hashlib
import json
import secrets
from uuid import uuid4

from src.models import (
    ApprovalGrant,
    ExecutedAction,
    HumanDecisionRecord,
    ProposedAction,
    ReviewDecision,
    WriteAttempt,
    WriteAttemptStatus,
    WriteErrorCode,
    WriteResult,
    WriteToolName,
)


class ApprovalAuthority:
    """Issue and consume one-time capabilities bound to exact reviewed actions."""

    def __init__(self) -> None:
        self._active: dict[str, ApprovalGrant] = {}
        self._consumed: set[str] = set()

    @staticmethod
    def action_fingerprint(action: ProposedAction) -> str:
        encoded = json.dumps(
            action.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def issue(
        self,
        *,
        request_id: str,
        action: ProposedAction,
        decision: HumanDecisionRecord,
    ) -> ApprovalGrant:
        if decision.decision != ReviewDecision.APPROVE or not decision.review_complete:
            raise ValueError("approval tokens require a completed approve decision")
        reviewed_actions = {
            reviewed.action_id: reviewed for reviewed in decision.reviewed_actions
        }
        if reviewed_actions.get(action.action_id) != action:
            raise ValueError("approved decision does not contain the exact action")
        if action.tool_name is None:
            raise ValueError("approval tokens can only authorize executable actions")
        grant = ApprovalGrant(
            token=f"apt_{secrets.token_urlsafe(32)}",
            request_id=request_id,
            action_id=action.action_id,
            tool_name=action.tool_name,
            action_fingerprint=self.action_fingerprint(action),
        )
        self._active[grant.token] = grant
        return grant

    def authorize_and_consume(
        self,
        *,
        token: str | None,
        request_id: str,
        action: ProposedAction,
        expected_tool: WriteToolName,
    ) -> WriteErrorCode | None:
        if token is None:
            return WriteErrorCode.APPROVAL_REQUIRED
        if token in self._consumed:
            return WriteErrorCode.TOKEN_ALREADY_USED
        grant = self._active.get(token)
        if grant is None:
            return WriteErrorCode.INVALID_APPROVAL_TOKEN
        if grant.tool_name != expected_tool or action.tool_name != expected_tool:
            return WriteErrorCode.TOOL_MISMATCH
        if (
            grant.request_id != request_id
            or grant.action_id != action.action_id
            or grant.action_fingerprint != self.action_fingerprint(action)
        ):
            return WriteErrorCode.ACTION_MISMATCH

        del self._active[token]
        self._consumed.add(token)
        return None


def _rejected_result(
    *,
    tool_name: WriteToolName,
    action: ProposedAction,
    error_code: WriteErrorCode,
) -> WriteResult:
    return WriteResult(
        success=False,
        attempt=WriteAttempt(
            attempt_id=str(uuid4()),
            tool_name=tool_name,
            action_id=action.action_id,
            property_id=action.property_id,
            target_record_id=action.target_record_id or "missing-target",
            approved=False,
            status=WriteAttemptStatus.REJECTED,
            error_code=error_code,
            message=f"Simulated write rejected: {error_code.value}.",
        ),
    )


def _executed_result(
    *,
    tool_name: WriteToolName,
    action: ProposedAction,
    result: dict[str, str | bool],
) -> WriteResult:
    execution_id = str(uuid4())
    target_record_id = action.target_record_id or "missing-target"
    return WriteResult(
        success=True,
        attempt=WriteAttempt(
            attempt_id=str(uuid4()),
            tool_name=tool_name,
            action_id=action.action_id,
            property_id=action.property_id,
            target_record_id=target_record_id,
            approved=True,
            status=WriteAttemptStatus.EXECUTED,
            message="Approved simulated write executed.",
        ),
        execution=ExecutedAction(
            execution_id=execution_id,
            tool_name=tool_name,
            action_id=action.action_id,
            property_id=action.property_id,
            target_record_id=target_record_id,
            result=result,
        ),
    )


def _authorize(
    *,
    authority: ApprovalAuthority,
    approval_token: str | None,
    request_id: str,
    action: ProposedAction,
    tool_name: WriteToolName,
) -> WriteResult | None:
    error = authority.authorize_and_consume(
        token=approval_token,
        request_id=request_id,
        action=action,
        expected_tool=tool_name,
    )
    if error is not None:
        return _rejected_result(
            tool_name=tool_name,
            action=action,
            error_code=error,
        )
    return None


def send_guest_message(
    *,
    action: ProposedAction,
    approval_token: str | None,
    request_id: str,
    authority: ApprovalAuthority,
) -> WriteResult:
    """Simulate replying to the guest-message record named by an approved action."""

    rejected = _authorize(
        authority=authority,
        approval_token=approval_token,
        request_id=request_id,
        action=action,
        tool_name=WriteToolName.SEND_GUEST_MESSAGE,
    )
    if rejected is not None:
        return rejected
    return _executed_result(
        tool_name=WriteToolName.SEND_GUEST_MESSAGE,
        action=action,
        result={
            "source_message_id": action.target_record_id or "",
            "message": action.parameters["message"],
            "delivery": "simulated",
        },
    )


def send_cleaner_message(
    *,
    action: ProposedAction,
    approval_token: str | None,
    request_id: str,
    authority: ApprovalAuthority,
) -> WriteResult:
    """Simulate messaging the cleaner linked to an approved cleaning action."""

    rejected = _authorize(
        authority=authority,
        approval_token=approval_token,
        request_id=request_id,
        action=action,
        tool_name=WriteToolName.SEND_CLEANER_MESSAGE,
    )
    if rejected is not None:
        return rejected
    return _executed_result(
        tool_name=WriteToolName.SEND_CLEANER_MESSAGE,
        action=action,
        result={
            "cleaning_id": action.target_record_id or "",
            "message": action.parameters["message"],
            "delivery": "simulated",
        },
    )


def update_maintenance_status(
    *,
    action: ProposedAction,
    approval_token: str | None,
    request_id: str,
    authority: ApprovalAuthority,
) -> WriteResult:
    """Simulate the exact maintenance status change approved by the host."""

    rejected = _authorize(
        authority=authority,
        approval_token=approval_token,
        request_id=request_id,
        action=action,
        tool_name=WriteToolName.UPDATE_MAINTENANCE_STATUS,
    )
    if rejected is not None:
        return rejected
    return _executed_result(
        tool_name=WriteToolName.UPDATE_MAINTENANCE_STATUS,
        action=action,
        result={
            "maintenance_ticket_id": action.target_record_id or "",
            "status": action.parameters["status"],
            "update": "simulated",
        },
    )


WRITE_TOOL_RUNNERS = {
    WriteToolName.SEND_GUEST_MESSAGE: send_guest_message,
    WriteToolName.SEND_CLEANER_MESSAGE: send_cleaner_message,
    WriteToolName.UPDATE_MAINTENANCE_STATUS: update_maintenance_status,
}
