"""Timezone-aware operating-date and natural calendar-scope helpers."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "America/Los_Angeles"
WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def operating_timezone(name: str | None = None) -> ZoneInfo:
    """Return the configured operating timezone with a safe default."""

    timezone_name = name or os.getenv("STAYOPS_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def current_operating_date(
    now: datetime | None = None,
    *,
    timezone_name: str | None = None,
) -> date:
    """Return today's calendar date in the property's operating timezone."""

    timezone = operating_timezone(timezone_name)
    if now is None:
        return datetime.now(timezone).date()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    return now.astimezone(timezone).date()


def _date_range(start: date, end: date) -> str:
    return f"{start.isoformat()}/{end.isoformat()}"


def _week_start(reference_date: date, offset_weeks: int = 0) -> date:
    return (
        reference_date
        - timedelta(days=reference_date.weekday())
        + timedelta(weeks=offset_weeks)
    )


def _relative_weekday(
    reference_date: date,
    weekday: int,
    modifier: str | None,
) -> date:
    if modifier == "last":
        days_back = (reference_date.weekday() - weekday) % 7 or 7
        return reference_date - timedelta(days=days_back)
    if modifier == "this":
        return _week_start(reference_date) + timedelta(days=weekday)
    days_ahead = (weekday - reference_date.weekday()) % 7
    if modifier == "next" and days_ahead == 0:
        days_ahead = 7
    return reference_date + timedelta(days=days_ahead)


def resolve_date_scope(query: str, reference_date: date) -> str | None:
    """Resolve supported calendar language to one ISO date or inclusive range."""

    normalized = query.casefold().replace("’", "'")
    iso_dates = re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", normalized)
    valid_iso_dates: list[date] = []
    for value in iso_dates[:2]:
        try:
            valid_iso_dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    if len(valid_iso_dates) == 2:
        start, end = sorted(valid_iso_dates)
        return _date_range(start, end)
    if len(valid_iso_dates) == 1:
        return valid_iso_dates[0].isoformat()

    if re.search(r"\bday after tomorrow\b", normalized):
        return (reference_date + timedelta(days=2)).isoformat()
    if re.search(r"\bday before yesterday\b", normalized):
        return (reference_date - timedelta(days=2)).isoformat()
    if re.search(r"\btomorrow\b", normalized):
        return (reference_date + timedelta(days=1)).isoformat()
    if re.search(r"\byesterday\b", normalized):
        return (reference_date - timedelta(days=1)).isoformat()
    if re.search(r"\btoday(?:'s)?\b", normalized):
        return reference_date.isoformat()

    weekday_match = re.search(
        r"\b(?:(next|this|last)\s+)?"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b",
        normalized,
    )
    if weekday_match is not None:
        modifier, weekday_name = weekday_match.groups()
        return _relative_weekday(
            reference_date,
            WEEKDAY_NAMES[weekday_name],
            modifier,
        ).isoformat()

    if re.search(r"\b(?:last|previous)\s+weekday\b", normalized):
        candidate = reference_date - timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate.isoformat()
    if re.search(r"\bnext\s+weekday\b", normalized):
        candidate = reference_date + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    if re.search(r"\bthis\s+weekday\b", normalized):
        candidate = reference_date
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    weekday_period = re.search(
        r"\b(?:(this|next|last)\s+(?:week(?:'s)?\s+)?)?weekdays\b",
        normalized,
    )
    if weekday_period is not None:
        modifier = weekday_period.group(1)
        offset = 1 if modifier == "next" else -1 if modifier == "last" else 0
        monday = _week_start(reference_date, offset)
        return _date_range(monday, monday + timedelta(days=4))

    weekend_match = re.search(
        r"\b(?:(this|next|last)\s+)?weekends?\b",
        normalized,
    )
    if weekend_match is not None:
        modifier = weekend_match.group(1)
        offset = 1 if modifier == "next" else -1 if modifier == "last" else 0
        saturday = _week_start(reference_date, offset) + timedelta(days=5)
        return _date_range(saturday, saturday + timedelta(days=1))

    next_days = re.search(r"\bnext\s+(\d{1,2})\s+days?\b", normalized)
    if next_days is not None:
        days = int(next_days.group(1))
        if days > 0:
            return _date_range(reference_date, reference_date + timedelta(days=days))

    if re.search(r"\bnext week\b", normalized):
        next_monday = _week_start(reference_date, 1)
        return _date_range(next_monday, next_monday + timedelta(days=6))
    if re.search(r"\bthis week\b", normalized):
        this_sunday = _week_start(reference_date) + timedelta(days=6)
        return _date_range(reference_date, this_sunday)
    if re.search(r"\bupcoming\b", normalized):
        return _date_range(reference_date, reference_date + timedelta(days=7))
    return None
