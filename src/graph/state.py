"""Shared typed LangGraph state for the complete StayOps workflow."""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import uuid4


class StayOpsState(TypedDict):
    request_id: str
    host_query: str
    intent: str
    property_scope: list[str]
    date_scope: str | None
    write_requested: bool
    property_context: dict[str, Any]
    reservation_context: dict[str, Any]
    booking_findings: list[dict[str, Any]]
    guest_findings: list[dict[str, Any]]
    turnover_findings: list[dict[str, Any]]
    maintenance_findings: list[dict[str, Any]]
    operational_findings: list[dict[str, Any]]
    priority_items: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    requires_human_review: bool
    human_decision: dict[str, Any] | None
    executed_actions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
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
        property_context={},
        reservation_context={},
        booking_findings=[],
        guest_findings=[],
        turnover_findings=[],
        maintenance_findings=[],
        operational_findings=[],
        priority_items=[],
        proposed_actions=[],
        requires_human_review=False,
        human_decision=None,
        executed_actions=[],
        errors=[],
        final_response="",
    )
