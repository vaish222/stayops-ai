"""JSON-backed, read-only operational tools with deterministic filtering."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from datetime import date
from json import JSONDecodeError
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.models import (
    CleaningSchedule,
    GuestMessage,
    MaintenanceStatus,
    MaintenanceTicket,
    Property,
    Reservation,
)
from src.tools.contracts import (
    ReadResult,
    ReadToolName,
    ToolError,
    ToolErrorCode,
    ToolMetadata,
)
from src.tools.failures import FailureSimulator


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RecordT = TypeVar("RecordT", bound=BaseModel)


def _filter_metadata(
    property_ids: frozenset[str] | None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, str | list[str] | None]:
    filters: dict[str, str | list[str] | None] = {
        "property_ids": sorted(property_ids) if property_ids is not None else None,
    }
    if start_date is not None or end_date is not None:
        filters["start_date"] = (
            start_date.isoformat()
            if isinstance(start_date, date)
            else str(start_date) if start_date is not None else None
        )
        filters["end_date"] = (
            end_date.isoformat()
            if isinstance(end_date, date)
            else str(end_date) if end_date is not None else None
        )
    return filters


def _failure_result(
    tool_name: ReadToolName,
    filters: dict[str, str | list[str] | None],
    error: ToolError,
) -> ReadResult[RecordT]:
    return ReadResult[RecordT](
        success=False,
        metadata=ToolMetadata(
            tool_name=tool_name,
            returned_count=0,
            filters=filters,
        ),
        error=error,
    )


def _success_result(
    tool_name: ReadToolName,
    filters: dict[str, str | list[str] | None],
    items: list[RecordT],
) -> ReadResult[RecordT]:
    return ReadResult[RecordT](
        success=True,
        items=items,
        metadata=ToolMetadata(
            tool_name=tool_name,
            returned_count=len(items),
            filters=filters,
        ),
    )


def _normalize_property_ids(
    property_ids: Collection[str] | None,
    tool_name: ReadToolName,
) -> tuple[frozenset[str] | None, ToolError | None]:
    if property_ids is None:
        return None, None
    if isinstance(property_ids, str):
        return None, ToolError(
            code=ToolErrorCode.INVALID_FILTER,
            message="property_ids must be a collection of IDs, not a single string.",
            tool_name=tool_name,
            retryable=False,
            details={"field": "property_ids"},
        )
    if any(not isinstance(value, str) or not value.strip() for value in property_ids):
        return None, ToolError(
            code=ToolErrorCode.INVALID_FILTER,
            message="Every property_ids value must be a non-empty string.",
            tool_name=tool_name,
            retryable=False,
            details={"field": "property_ids"},
        )
    return frozenset(property_ids), None


def _validate_date_range(
    start_date: date | None,
    end_date: date | None,
    tool_name: ReadToolName,
) -> ToolError | None:
    if start_date is not None and not isinstance(start_date, date):
        return ToolError(
            code=ToolErrorCode.INVALID_FILTER,
            message="start_date must be a date.",
            tool_name=tool_name,
            retryable=False,
            details={"field": "start_date"},
        )
    if end_date is not None and not isinstance(end_date, date):
        return ToolError(
            code=ToolErrorCode.INVALID_FILTER,
            message="end_date must be a date.",
            tool_name=tool_name,
            retryable=False,
            details={"field": "end_date"},
        )
    if start_date is not None and end_date is not None and start_date > end_date:
        return ToolError(
            code=ToolErrorCode.INVALID_FILTER,
            message="start_date cannot be after end_date.",
            tool_name=tool_name,
            retryable=False,
            details={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
    return None


def _load_records(
    data_dir: str | Path,
    filename: str,
    model: type[RecordT],
    tool_name: ReadToolName,
) -> tuple[list[RecordT], ToolError | None]:
    path = Path(data_dir) / filename
    try:
        with path.open(encoding="utf-8") as data_file:
            payload = json.load(data_file)
    except OSError as exc:
        return [], ToolError(
            code=ToolErrorCode.DATA_UNAVAILABLE,
            message=f"Operational data is unavailable for {tool_name.value}.",
            tool_name=tool_name,
            retryable=True,
            details={"path": str(path), "reason": str(exc)},
        )
    except JSONDecodeError as exc:
        return [], ToolError(
            code=ToolErrorCode.INVALID_DATA,
            message=f"Operational data is malformed for {tool_name.value}.",
            tool_name=tool_name,
            retryable=False,
            details={"path": str(path), "reason": str(exc)},
        )

    if not isinstance(payload, list):
        return [], ToolError(
            code=ToolErrorCode.INVALID_DATA,
            message=f"Operational data must be a JSON array for {tool_name.value}.",
            tool_name=tool_name,
            retryable=False,
            details={"path": str(path)},
        )

    try:
        return [model.model_validate(item) for item in payload], None
    except ValidationError as exc:
        return [], ToolError(
            code=ToolErrorCode.INVALID_DATA,
            message=f"Operational data failed schema validation for {tool_name.value}.",
            tool_name=tool_name,
            retryable=False,
            details={"path": str(path), "reason": str(exc)},
        )


def _read_and_filter(
    *,
    tool_name: ReadToolName,
    filename: str,
    model: type[RecordT],
    filters: dict[str, str | list[str] | None],
    predicate: Callable[[RecordT], bool],
    data_dir: str | Path,
    failure_simulator: FailureSimulator | None,
) -> ReadResult[RecordT]:
    if failure_simulator is not None:
        simulated_error = failure_simulator.check(tool_name)
        if simulated_error is not None:
            return _failure_result(tool_name, filters, simulated_error)

    records, load_error = _load_records(data_dir, filename, model, tool_name)
    if load_error is not None:
        return _failure_result(tool_name, filters, load_error)
    return _success_result(tool_name, filters, [item for item in records if predicate(item)])


def _date_is_in_range(
    value: date,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    return (start_date is None or value >= start_date) and (
        end_date is None or value <= end_date
    )


def get_properties(
    property_ids: Collection[str] | None = None,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> ReadResult[Property]:
    """Return all properties or only the requested property IDs."""

    tool_name = ReadToolName.GET_PROPERTIES
    normalized_ids, filter_error = _normalize_property_ids(property_ids, tool_name)
    filters = _filter_metadata(normalized_ids)
    if filter_error is not None:
        return _failure_result(tool_name, filters, filter_error)

    return _read_and_filter(
        tool_name=tool_name,
        filename="properties.json",
        model=Property,
        filters=filters,
        predicate=lambda item: normalized_ids is None or item.id in normalized_ids,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
    )


def get_reservations(
    property_ids: Collection[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> ReadResult[Reservation]:
    """Return stays that overlap the inclusive operational date range."""

    tool_name = ReadToolName.GET_RESERVATIONS
    normalized_ids, filter_error = _normalize_property_ids(property_ids, tool_name)
    filter_error = filter_error or _validate_date_range(start_date, end_date, tool_name)
    filters = _filter_metadata(normalized_ids, start_date, end_date)
    if filter_error is not None:
        return _failure_result(tool_name, filters, filter_error)

    def matches(item: Reservation) -> bool:
        property_matches = normalized_ids is None or item.property_id in normalized_ids
        range_overlaps = (
            (start_date is None or item.check_out_date >= start_date)
            and (end_date is None or item.check_in_date <= end_date)
        )
        return property_matches and range_overlaps

    return _read_and_filter(
        tool_name=tool_name,
        filename="reservations.json",
        model=Reservation,
        filters=filters,
        predicate=matches,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
    )


def get_guest_messages(
    property_ids: Collection[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> ReadResult[GuestMessage]:
    """Return messages received or sent on local calendar dates in the range."""

    tool_name = ReadToolName.GET_GUEST_MESSAGES
    normalized_ids, filter_error = _normalize_property_ids(property_ids, tool_name)
    filter_error = filter_error or _validate_date_range(start_date, end_date, tool_name)
    filters = _filter_metadata(normalized_ids, start_date, end_date)
    if filter_error is not None:
        return _failure_result(tool_name, filters, filter_error)

    return _read_and_filter(
        tool_name=tool_name,
        filename="guest_messages.json",
        model=GuestMessage,
        filters=filters,
        predicate=lambda item: (
            (normalized_ids is None or item.property_id in normalized_ids)
            and _date_is_in_range(item.received_at.date(), start_date, end_date)
        ),
        data_dir=data_dir,
        failure_simulator=failure_simulator,
    )


def get_cleaning_schedule(
    property_ids: Collection[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> ReadResult[CleaningSchedule]:
    """Return cleaning jobs scheduled within the inclusive date range."""

    tool_name = ReadToolName.GET_CLEANING_SCHEDULE
    normalized_ids, filter_error = _normalize_property_ids(property_ids, tool_name)
    filter_error = filter_error or _validate_date_range(start_date, end_date, tool_name)
    filters = _filter_metadata(normalized_ids, start_date, end_date)
    if filter_error is not None:
        return _failure_result(tool_name, filters, filter_error)

    return _read_and_filter(
        tool_name=tool_name,
        filename="cleaning_schedule.json",
        model=CleaningSchedule,
        filters=filters,
        predicate=lambda item: (
            (normalized_ids is None or item.property_id in normalized_ids)
            and _date_is_in_range(item.scheduled_date, start_date, end_date)
        ),
        data_dir=data_dir,
        failure_simulator=failure_simulator,
    )


def get_maintenance_tickets(
    property_ids: Collection[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    failure_simulator: FailureSimulator | None = None,
) -> ReadResult[MaintenanceTicket]:
    """Return tickets active at any point in the inclusive date range.

    An unresolved ticket remains active after its creation date. A resolved
    ticket overlaps the range from creation through its final update date.
    """

    tool_name = ReadToolName.GET_MAINTENANCE_TICKETS
    normalized_ids, filter_error = _normalize_property_ids(property_ids, tool_name)
    filter_error = filter_error or _validate_date_range(start_date, end_date, tool_name)
    filters = _filter_metadata(normalized_ids, start_date, end_date)
    if filter_error is not None:
        return _failure_result(tool_name, filters, filter_error)

    def matches(item: MaintenanceTicket) -> bool:
        if normalized_ids is not None and item.property_id not in normalized_ids:
            return False
        if end_date is not None and item.created_at.date() > end_date:
            return False
        if (
            start_date is not None
            and item.status == MaintenanceStatus.RESOLVED
            and item.updated_at.date() < start_date
        ):
            return False
        return True

    return _read_and_filter(
        tool_name=tool_name,
        filename="maintenance_tickets.json",
        model=MaintenanceTicket,
        filters=filters,
        predicate=matches,
        data_dir=data_dir,
        failure_simulator=failure_simulator,
    )
