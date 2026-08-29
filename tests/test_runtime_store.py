"""Persistent simulated-write overlay tests."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.models import ExecutedAction, ProposedAction, WriteToolName
from src.tools import (
    SimulatedOperationsStore,
    get_cleaning_schedule,
    get_guest_messages,
    get_maintenance_tickets,
)


REFERENCE_DATE = date(2026, 8, 28)
SIMULATED_NOW = datetime(2026, 8, 28, 23, 59, tzinfo=timezone.utc)


def _record(
    store: SimulatedOperationsStore,
    *,
    action_id: str,
    property_id: str,
    tool_name: WriteToolName,
    target_record_id: str,
    description: str,
    parameters: dict[str, str],
) -> None:
    action = ProposedAction(
        action_id=action_id,
        property_id=property_id,
        action_type=(
            "update_record"
            if tool_name == WriteToolName.UPDATE_MAINTENANCE_STATUS
            else "send_message"
        ),
        description=description,
        source_finding_ids=[f"finding:{action_id}"],
        tool_name=tool_name,
        target_record_id=target_record_id,
        parameters=parameters,
    )
    execution = ExecutedAction(
        execution_id=f"execution:{action_id}",
        tool_name=tool_name,
        action_id=action_id,
        property_id=property_id,
        target_record_id=target_record_id,
        result={"delivery": "simulated"},
    )
    store.record_execution(
        request_id="runtime-overlay-test",
        action=action,
        execution=execution,
    )
    # Re-recording an execution ID is idempotent.
    store.record_execution(
        request_id="runtime-overlay-test",
        action=action,
        execution=execution,
    )


def test_runtime_store_persists_and_merges_all_simulated_write_types(tmp_path) -> None:
    store = SimulatedOperationsStore(tmp_path, clock=lambda: SIMULATED_NOW)
    _record(
        store,
        action_id="action:guest",
        property_id="prop_pine_house",
        tool_name=WriteToolName.SEND_GUEST_MESSAGE,
        target_record_id="msg_pine_001",
        description="We are checking this now.",
        parameters={"message": "We are checking this now."},
    )
    _record(
        store,
        action_id="action:cleaner",
        property_id="prop_lake_house",
        tool_name=WriteToolName.SEND_CLEANER_MESSAGE,
        target_record_id="clean_lake_001",
        description="Please confirm the turnover.",
        parameters={"message": "Please confirm the turnover."},
    )
    _record(
        store,
        action_id="action:maintenance",
        property_id="prop_pine_house",
        tool_name=WriteToolName.UPDATE_MAINTENANCE_STATUS,
        target_record_id="maint_pine_001",
        description="Start work on this ticket.",
        parameters={"status": "in_progress"},
    )

    messages = get_guest_messages(
        ["prop_pine_house"],
        REFERENCE_DATE,
        REFERENCE_DATE,
        runtime_store=store,
    ).items
    source_message = next(item for item in messages if item.id == "msg_pine_001")
    outbound = next(item for item in messages if item.direction == "outbound")
    assert source_message.responded_at == SIMULATED_NOW
    assert outbound.body == "We are checking this now."
    assert outbound.requires_response is False

    cleanings = get_cleaning_schedule(
        ["prop_lake_house"],
        REFERENCE_DATE,
        REFERENCE_DATE,
        runtime_store=store,
    ).items
    assert "Simulated reminder sent" in cleanings[0].notes

    tickets = get_maintenance_tickets(
        ["prop_pine_house"],
        REFERENCE_DATE,
        REFERENCE_DATE,
        runtime_store=store,
    ).items
    ticket = next(item for item in tickets if item.id == "maint_pine_001")
    assert ticket.status == "in_progress"
    assert ticket.updated_at == SIMULATED_NOW

    assert len(store.action_history()) == 3
    assert len(json.loads((tmp_path / "outbound_messages.json").read_text())) == 2
    assert len(json.loads((tmp_path / "record_updates.json").read_text())) == 3
