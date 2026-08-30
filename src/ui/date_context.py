"""Pure date-context helpers for the StayOps presentation layer."""

from __future__ import annotations

from datetime import date, timedelta


def parse_date_scope(value: str | None) -> tuple[date, date] | None:
    """Parse one ISO date or inclusive ISO range from structured graph state."""

    if not value:
        return None
    parts = value.split("/")
    if len(parts) not in {1, 2}:
        return None
    try:
        parsed = [date.fromisoformat(part) for part in parts]
    except ValueError:
        return None
    start, end = parsed[0], parsed[-1]
    if start > end:
        return None
    return start, end


def single_date_from_scope(value: str | None) -> date | None:
    """Return a date only when the structured scope represents one day."""

    parsed = parse_date_scope(value)
    if parsed is None or parsed[0] != parsed[1]:
        return None
    return parsed[0]


def format_short_date(value: date, today: date) -> str:
    """Format a compact calendar date, including the year when it adds context."""

    label = f"{value.strftime('%b')} {value.day}"
    return f"{label}, {value.year}" if value.year != today.year else label


def format_date_context(value: date, today: date) -> str:
    """Format one date with a relative label when it is close to today."""

    short_date = format_short_date(value, today)
    if value == today:
        return f"Today · {short_date}"
    if value == today + timedelta(days=1):
        return f"Tomorrow · {short_date}"
    if value == today - timedelta(days=1):
        return f"Yesterday · {short_date}"
    return short_date


def format_scope_context(value: str | None, today: date) -> str:
    """Format a structured single-date or range scope for operator-facing UI."""

    parsed = parse_date_scope(value)
    if parsed is None:
        return "Requested period"
    start, end = parsed
    if start == end:
        return format_date_context(start, today)
    if start.year == end.year == today.year and start.month == end.month:
        return f"{start.strftime('%b')} {start.day}–{end.day}"
    return f"{format_short_date(start, today)}–{format_short_date(end, today)}"


def format_answer_date_context(value: str | None, today: date) -> str:
    """Format the leading date-context sentence for a StayOps answer."""

    single_date = single_date_from_scope(value)
    if single_date is None:
        if parse_date_scope(value) is None:
            return "For the requested period"
        return f"For {format_scope_context(value, today)}"
    context = format_date_context(single_date, today)
    if single_date == today + timedelta(days=1):
        return f"Looking ahead to {context}"
    if single_date == today - timedelta(days=1):
        return f"Looking back to {context}"
    return f"For {context}"


def readiness_copy(value: date, today: date, property_count: int) -> str:
    """Return date-aware Portfolio Overview supporting copy."""

    if value == today:
        subject = "Today's readiness"
    elif value == today + timedelta(days=1):
        subject = "Tomorrow's readiness"
    elif value == today - timedelta(days=1):
        subject = "Yesterday's readiness"
    else:
        subject = f"Readiness for {format_short_date(value, today)}"
    return f"{subject} across all {property_count} properties."


def operations_copy(value: date, today: date) -> str:
    """Return date-aware Operations Workspace supporting copy."""

    if value == today:
        return "Today's operations"
    if value == today + timedelta(days=1):
        return "Tomorrow's operations"
    if value == today - timedelta(days=1):
        return "Yesterday's operations"
    return f"Operations for {format_short_date(value, today)}"
