"""Durable runtime overlay for approval-protected simulated operations."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from src.models import (
    CleaningSchedule,
    ExecutedAction,
    GuestMessage,
    MaintenanceTicket,
    MaintenanceStatus,
    MessageDirection,
    ProposedAction,
    WriteToolName,
)


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "data" / "runtime"


class SimulatedOperationsStore:
    """Persist simulated writes separately from the immutable demo fixtures."""

    OUTBOUND_MESSAGES_FILE = "outbound_messages.json"
    RECORD_UPDATES_FILE = "record_updates.json"
    ACTION_HISTORY_FILE = "action_history.json"

    def __init__(
        self,
        runtime_dir: str | Path = DEFAULT_RUNTIME_DIR,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def _read(self, filename: str) -> list[dict[str, Any]]:
        path = self.runtime_dir / filename
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Simulated runtime data is unavailable: {path}") from exc
        if not isinstance(payload, list):
            raise RuntimeError(f"Simulated runtime data must be a JSON array: {path}")
        return payload

    def _write(self, filename: str, records: list[dict[str, Any]]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.runtime_dir / filename
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(records, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def record_execution(
        self,
        *,
        request_id: str,
        action: ProposedAction,
        execution: ExecutedAction,
    ) -> dict[str, Any]:
        """Record one successful simulation and return its history event."""

        occurred_at = self._clock()
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        timestamp = occurred_at.isoformat()
        history_event = {
            "event_id": f"event_{uuid4().hex}",
            "execution_id": execution.execution_id,
            "request_id": request_id,
            "action_id": action.action_id,
            "property_id": action.property_id,
            "tool_name": action.tool_name.value if action.tool_name else None,
            "target_record_id": action.target_record_id,
            "description": action.description,
            "status": "executed",
            "occurred_at": timestamp,
            "simulated": True,
        }

        with self._lock:
            history = self._read(self.ACTION_HISTORY_FILE)
            existing = next(
                (
                    event
                    for event in history
                    if event.get("execution_id") == execution.execution_id
                ),
                None,
            )
            if existing is not None:
                return existing

            outbound = self._read(self.OUTBOUND_MESSAGES_FILE)
            updates = self._read(self.RECORD_UPDATES_FILE)
            if action.tool_name in {
                WriteToolName.SEND_GUEST_MESSAGE,
                WriteToolName.SEND_CLEANER_MESSAGE,
            } and not any(
                event.get("execution_id") == execution.execution_id
                for event in outbound
            ):
                outbound.append(
                    {
                        "message_id": f"runtime_msg_{uuid4().hex}",
                        "execution_id": execution.execution_id,
                        "request_id": request_id,
                        "action_id": action.action_id,
                        "property_id": action.property_id,
                        "target_record_id": action.target_record_id,
                        "recipient_type": (
                            "guest"
                            if action.tool_name == WriteToolName.SEND_GUEST_MESSAGE
                            else "cleaner"
                        ),
                        "body": action.parameters["message"],
                        "sent_at": timestamp,
                        "delivery": "simulated",
                    }
                )
            if action.tool_name == WriteToolName.SEND_GUEST_MESSAGE:
                update_event = {
                    "update_id": f"runtime_update_{uuid4().hex}",
                    "execution_id": execution.execution_id,
                    "record_type": "guest_message",
                    "record_id": action.target_record_id,
                    "changes": {"responded_at": timestamp},
                    "updated_at": timestamp,
                    "simulated": True,
                }
            elif action.tool_name == WriteToolName.SEND_CLEANER_MESSAGE:
                update_event = {
                    "update_id": f"runtime_update_{uuid4().hex}",
                    "execution_id": execution.execution_id,
                    "record_type": "cleaning_schedule",
                    "record_id": action.target_record_id,
                    "changes": {"reminder_sent_at": timestamp},
                    "updated_at": timestamp,
                    "simulated": True,
                }
            elif action.tool_name == WriteToolName.UPDATE_MAINTENANCE_STATUS:
                update_event = {
                    "update_id": f"runtime_update_{uuid4().hex}",
                    "execution_id": execution.execution_id,
                    "record_type": "maintenance_ticket",
                    "record_id": action.target_record_id,
                    "changes": {"status": action.parameters["status"]},
                    "updated_at": timestamp,
                    "simulated": True,
                }
            else:
                update_event = None
            if update_event is not None and not any(
                event.get("execution_id") == execution.execution_id
                for event in updates
            ):
                updates.append(update_event)

            # Write event details before committing history. A history row is the
            # marker that the complete simulated operation was recorded.
            self._write(self.OUTBOUND_MESSAGES_FILE, outbound)
            self._write(self.RECORD_UPDATES_FILE, updates)
            history.append(history_event)
            self._write(self.ACTION_HISTORY_FILE, history)
        return history_event

    def action_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read(self.ACTION_HISTORY_FILE)

    def _updates_for(self, record_type: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self._read(self.RECORD_UPDATES_FILE)
            if event.get("record_type") == record_type
        ]

    def apply_guest_messages(
        self,
        records: Sequence[GuestMessage],
    ) -> list[GuestMessage]:
        """Overlay response timestamps and append simulated outbound replies."""

        with self._lock:
            updates = self._updates_for("guest_message")
            outbound = [
                event
                for event in self._read(self.OUTBOUND_MESSAGES_FILE)
                if event.get("recipient_type") == "guest"
            ]
        update_by_id = {event["record_id"]: event for event in updates}
        source_by_id = {record.id: record for record in records}
        overlaid: list[GuestMessage] = []
        for record in records:
            event = update_by_id.get(record.id)
            if event is None:
                overlaid.append(record)
                continue
            overlaid.append(
                record.model_copy(
                    update={
                        "responded_at": datetime.fromisoformat(
                            event["changes"]["responded_at"]
                        )
                    }
                )
            )
        for event in outbound:
            source = source_by_id.get(event.get("target_record_id"))
            if source is None:
                continue
            overlaid.append(
                GuestMessage(
                    id=f"msg_runtime_{event['message_id'].removeprefix('runtime_msg_')}",
                    property_id=source.property_id,
                    reservation_id=source.reservation_id,
                    guest_id=source.guest_id,
                    guest_name=source.guest_name,
                    received_at=datetime.fromisoformat(event["sent_at"]),
                    direction=MessageDirection.OUTBOUND,
                    category=source.category,
                    urgency=source.urgency,
                    body=event["body"],
                    requires_response=False,
                    is_synthetic=True,
                )
            )
        return overlaid

    def apply_cleanings(
        self,
        records: Sequence[CleaningSchedule],
    ) -> list[CleaningSchedule]:
        with self._lock:
            updates = self._updates_for("cleaning_schedule")
        latest_by_id = {event["record_id"]: event for event in updates}
        overlaid: list[CleaningSchedule] = []
        for record in records:
            event = latest_by_id.get(record.id)
            if event is None:
                overlaid.append(record)
                continue
            reminder_at = datetime.fromisoformat(
                event["changes"]["reminder_sent_at"]
            ).strftime("%b %d, %Y at %I:%M %p")
            note = f"Simulated reminder sent {reminder_at}."
            if record.notes and note in record.notes:
                notes = record.notes
            else:
                notes = f"{record.notes} {note}" if record.notes else note
            overlaid.append(record.model_copy(update={"notes": notes}))
        return overlaid

    def apply_maintenance(
        self,
        records: Sequence[MaintenanceTicket],
    ) -> list[MaintenanceTicket]:
        with self._lock:
            updates = self._updates_for("maintenance_ticket")
        latest_by_id = {event["record_id"]: event for event in updates}
        overlaid: list[MaintenanceTicket] = []
        for record in records:
            event = latest_by_id.get(record.id)
            if event is None:
                overlaid.append(record)
                continue
            updated = record.model_dump()
            updated["status"] = MaintenanceStatus(event["changes"]["status"])
            updated["updated_at"] = max(
                record.updated_at,
                datetime.fromisoformat(event["updated_at"]),
            )
            if updated["status"] == MaintenanceStatus.RESOLVED:
                updated["resolution_notes"] = "Resolved in the StayOps simulation."
            else:
                updated["resolution_notes"] = None
            overlaid.append(MaintenanceTicket.model_validate(updated))
        return overlaid
