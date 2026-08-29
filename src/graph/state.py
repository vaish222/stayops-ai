"""Shared typed LangGraph state for the complete StayOps workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4


class AgentRunLog(TypedDict):
    agent: Literal["booking", "guest", "turnover", "maintenance"]
    status: Literal["succeeded", "failed"]
    latency_ms: float
    finding_count: int
    warning_count: int
    analyzed_record_count: int
    error: str | None


class WorkflowError(TypedDict, total=False):
    stage: Literal[
        "context_loading",
        "specialist_execution",
        "synthesis_execution",
        "risk_gate_execution",
        "action_execution",
    ]
    code: str
    message: str
    component: str
    tool_name: str
    retryable: bool
    attempts: int
    details: dict[str, Any]


class StayOpsState(TypedDict):
    request_id: str
    host_query: str
    intent: str
    property_scope: list[str]
    date_scope: str | None
    write_requested: bool
    selected_specialists: list[str]
    property_context: dict[str, dict[str, Any]]
    reservation_context: dict[str, dict[str, Any]]
    guest_message_context: dict[str, dict[str, Any]]
    cleaning_context: dict[str, dict[str, Any]]
    maintenance_context: dict[str, dict[str, Any]]
    booking_findings: list[dict[str, Any]]
    guest_findings: list[dict[str, Any]]
    turnover_findings: list[dict[str, Any]]
    maintenance_findings: list[dict[str, Any]]
    operational_findings: list[dict[str, Any]]
    priority_items: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    overall_status: str
    action_proposed: bool
    requires_human_review: bool
    review_reasons: list[dict[str, Any]]
    risk_gate_evaluated: bool
    human_decision: dict[str, Any] | None
    approval_grants: list[dict[str, Any]]
    action_attempts: list[dict[str, Any]]
    executed_actions: list[dict[str, Any]]
    agent_runs: Annotated[list[AgentRunLog], operator.add]
    errors: Annotated[list[WorkflowError], operator.add]
    final_response: str


def create_initial_state(host_query: str, request_id: str | None = None) -> StayOpsState:
    """Create a fully populated state before the request-router node runs."""

    return StayOpsState(
        request_id=request_id or str(uuid4()),
        host_query=host_query,
        intent="",
        property_scope=[],
        date_scope=None,
        write_requested=False,
        selected_specialists=[],
        property_context={},
        reservation_context={},
        guest_message_context={},
        cleaning_context={},
        maintenance_context={},
        booking_findings=[],
        guest_findings=[],
        turnover_findings=[],
        maintenance_findings=[],
        operational_findings=[],
        priority_items=[],
        proposed_actions=[],
        overall_status="",
        action_proposed=False,
        requires_human_review=False,
        review_reasons=[],
        risk_gate_evaluated=False,
        human_decision=None,
        approval_grants=[],
        action_attempts=[],
        executed_actions=[],
        agent_runs=[],
        errors=[],
        final_response="",
    )
