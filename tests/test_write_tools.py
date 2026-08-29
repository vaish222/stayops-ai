"""Phase 8 approval-token enforcement tests for simulated write tools."""

from __future__ import annotations

import pytest

from src.models import (
    ActionType,
    HumanDecisionRecord,
    ProposedAction,
    ReviewDecision,
    WriteErrorCode,
    WriteToolName,
)
from src.tools import (
    ApprovalAuthority,
    send_cleaner_message,
    send_guest_message,
    update_maintenance_status,
)


REQUEST_ID = "phase-8-tool-test"


def make_action(tool_name: WriteToolName) -> ProposedAction:
    if tool_name == WriteToolName.SEND_GUEST_MESSAGE:
        description = "Thanks for your message. I will follow up shortly."
        return ProposedAction(
            action_id="action:guest:test",
            property_id="prop_pine_house",
            action_type=ActionType.SEND_MESSAGE,
            description=description,
            source_finding_ids=["guest:test"],
            tool_name=tool_name,
            target_record_id="msg_pine_001",
            parameters={"message": description},
        )
    if tool_name == WriteToolName.SEND_CLEANER_MESSAGE:
        description = "Please confirm the scheduled turnover."
        return ProposedAction(
            action_id="action:cleaner:test",
            property_id="prop_lake_house",
            action_type=ActionType.SEND_MESSAGE,
            description=description,
            source_finding_ids=["turnover:test"],
            tool_name=tool_name,
            target_record_id="clean_lake_001",
            parameters={"message": description},
        )
    return ProposedAction(
        action_id="action:maintenance:test",
        property_id="prop_pine_house",
        action_type=ActionType.UPDATE_RECORD,
        description="Update the maintenance ticket status to in_progress.",
        source_finding_ids=["maintenance:test"],
        tool_name=tool_name,
        target_record_id="maint_pine_001",
        parameters={"status": "in_progress"},
    )


TOOL_CASES = [
    (WriteToolName.SEND_GUEST_MESSAGE, send_guest_message),
    (WriteToolName.SEND_CLEANER_MESSAGE, send_cleaner_message),
    (WriteToolName.UPDATE_MAINTENANCE_STATUS, update_maintenance_status),
]


def approved_decision(action: ProposedAction) -> HumanDecisionRecord:
    return HumanDecisionRecord(
        decision=ReviewDecision.APPROVE,
        action_ids=[action.action_id],
        review_complete=True,
        reviewed_actions=[action],
    )


@pytest.mark.parametrize(("tool_name", "runner"), TOOL_CASES)
def test_every_write_tool_rejects_missing_approval_and_logs_attempt(
    tool_name,
    runner,
) -> None:
    action = make_action(tool_name)

    result = runner(
        action=action,
        approval_token=None,
        request_id=REQUEST_ID,
        authority=ApprovalAuthority(),
    )

    assert result.success is False
    assert result.execution is None
    assert result.attempt.tool_name == tool_name
    assert result.attempt.action_id == action.action_id
    assert result.attempt.approved is False
    assert result.attempt.status == "rejected"
    assert result.attempt.error_code == WriteErrorCode.APPROVAL_REQUIRED


@pytest.mark.parametrize(("tool_name", "runner"), TOOL_CASES)
def test_every_write_tool_executes_exact_approved_action(tool_name, runner) -> None:
    authority = ApprovalAuthority()
    action = make_action(tool_name)
    grant = authority.issue(
        request_id=REQUEST_ID,
        action=action,
        decision=approved_decision(action),
    )

    result = runner(
        action=action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )

    assert result.success is True
    assert result.attempt.approved is True
    assert result.attempt.status == "executed"
    assert result.attempt.error_code is None
    assert result.execution is not None
    assert result.execution.tool_name == tool_name
    assert result.execution.action_id == action.action_id
    assert result.execution.target_record_id == action.target_record_id
    assert result.execution.simulated is True


def test_invalid_token_is_rejected_and_logged() -> None:
    action = make_action(WriteToolName.SEND_GUEST_MESSAGE)

    result = send_guest_message(
        action=action,
        approval_token="apt_not-a-real-approval-token-000000000000",
        request_id=REQUEST_ID,
        authority=ApprovalAuthority(),
    )

    assert result.attempt.error_code == WriteErrorCode.INVALID_APPROVAL_TOKEN
    assert result.execution is None


def test_token_is_bound_to_request_and_exact_action_content() -> None:
    authority = ApprovalAuthority()
    action = make_action(WriteToolName.SEND_GUEST_MESSAGE)
    grant = authority.issue(
        request_id=REQUEST_ID,
        action=action,
        decision=approved_decision(action),
    )
    edited_description = "This content was not approved."
    edited = action.model_copy(
        update={
            "description": edited_description,
            "parameters": {"message": edited_description},
        }
    )

    wrong_request = send_guest_message(
        action=action,
        approval_token=grant.token,
        request_id="different-request",
        authority=authority,
    )
    changed_action = send_guest_message(
        action=edited,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )
    approved = send_guest_message(
        action=action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )

    assert wrong_request.attempt.error_code == WriteErrorCode.ACTION_MISMATCH
    assert changed_action.attempt.error_code == WriteErrorCode.ACTION_MISMATCH
    assert approved.success is True


def test_token_cannot_authorize_a_different_tool() -> None:
    authority = ApprovalAuthority()
    cleaner_action = make_action(WriteToolName.SEND_CLEANER_MESSAGE)
    grant = authority.issue(
        request_id=REQUEST_ID,
        action=cleaner_action,
        decision=approved_decision(cleaner_action),
    )

    rejected = send_guest_message(
        action=cleaner_action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )
    approved = send_cleaner_message(
        action=cleaner_action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )

    assert rejected.attempt.error_code == WriteErrorCode.TOOL_MISMATCH
    assert approved.success is True


def test_approval_token_is_one_time_and_replay_is_logged() -> None:
    authority = ApprovalAuthority()
    action = make_action(WriteToolName.UPDATE_MAINTENANCE_STATUS)
    grant = authority.issue(
        request_id=REQUEST_ID,
        action=action,
        decision=approved_decision(action),
    )

    first = update_maintenance_status(
        action=action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )
    replay = update_maintenance_status(
        action=action,
        approval_token=grant.token,
        request_id=REQUEST_ID,
        authority=authority,
    )

    assert first.success is True
    assert replay.success is False
    assert replay.attempt.error_code == WriteErrorCode.TOKEN_ALREADY_USED
    assert replay.execution is None


@pytest.mark.parametrize("decision_type", [ReviewDecision.EDIT, ReviewDecision.REJECT])
def test_nonapproved_decision_cannot_mint_token(
    decision_type: ReviewDecision,
) -> None:
    authority = ApprovalAuthority()
    action = make_action(WriteToolName.SEND_GUEST_MESSAGE)
    decision = HumanDecisionRecord(
        decision=decision_type,
        action_ids=[action.action_id],
        review_complete=decision_type == ReviewDecision.REJECT,
        reviewed_actions=[action],
        edited_description=(
            action.description if decision_type == ReviewDecision.EDIT else None
        ),
    )

    with pytest.raises(ValueError, match="completed approve decision"):
        authority.issue(
            request_id=REQUEST_ID,
            action=action,
            decision=decision,
        )
