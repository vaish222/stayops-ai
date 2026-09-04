"""Timezone-aware operating-date and natural calendar-scope helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
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
MONTH_NAMES = {
    name: month
    for month, names in enumerate(
        (
            (),
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        )
    )
    for name in names
}


class DateNormalizationMethod(StrEnum):
    EXPLICIT_ISO = "explicit_iso"
    NAMED_MONTH = "named_month"
    RELATIVE_DAY = "relative_day"
    WEEKDAY = "weekday"
    WEEKDAY_PERIOD = "weekday_period"
    WEEKEND = "weekend"
    RELATIVE_RANGE = "relative_range"
    NONE = "none"


@dataclass(frozen=True)
class DateScopeResolution:
    scope: str | None
    method: DateNormalizationMethod


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


def resolve_date_scope_details(query: str, reference_date: date) -> DateScopeResolution:
    """Resolve calendar language and report the deterministic rule that matched."""

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
        return DateScopeResolution(_date_range(start, end), DateNormalizationMethod.EXPLICIT_ISO)
    if len(valid_iso_dates) == 1:
        return DateScopeResolution(
            valid_iso_dates[0].isoformat(),
            DateNormalizationMethod.EXPLICIT_ISO,
        )

    month_pattern = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
    named_date = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
        normalized,
    )
    if named_date is not None:
        month_name, day_value, year_value = named_date.groups()
        try:
            resolved = date(
                int(year_value) if year_value else reference_date.year,
                MONTH_NAMES[month_name],
                int(day_value),
            )
        except ValueError:
            pass
        else:
            if re.search(r"\bbefore\s+(?:the\s+)?$", normalized[: named_date.start()]):
                resolved -= timedelta(days=1)
            return DateScopeResolution(resolved.isoformat(), DateNormalizationMethod.NAMED_MONTH)

    if re.search(r"\bday after tomorrow\b", normalized):
        return DateScopeResolution(
            (reference_date + timedelta(days=2)).isoformat(),
            DateNormalizationMethod.RELATIVE_DAY,
        )
    if re.search(r"\bday before yesterday\b", normalized):
        return DateScopeResolution(
            (reference_date - timedelta(days=2)).isoformat(),
            DateNormalizationMethod.RELATIVE_DAY,
        )
    if re.search(r"\btomorrow\b", normalized):
        return DateScopeResolution(
            (reference_date + timedelta(days=1)).isoformat(),
            DateNormalizationMethod.RELATIVE_DAY,
        )
    if re.search(r"\byesterday\b", normalized):
        return DateScopeResolution(
            (reference_date - timedelta(days=1)).isoformat(),
            DateNormalizationMethod.RELATIVE_DAY,
        )
    if re.search(r"\btoday(?:'s)?\b", normalized):
        return DateScopeResolution(reference_date.isoformat(), DateNormalizationMethod.RELATIVE_DAY)

    weekday_match = re.search(
        r"\b(?:(next|this|last)\s+)?"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b",
        normalized,
    )
    if weekday_match is not None:
        modifier, weekday_name = weekday_match.groups()
        return DateScopeResolution(
            _relative_weekday(reference_date, WEEKDAY_NAMES[weekday_name], modifier).isoformat(),
            DateNormalizationMethod.WEEKDAY,
        )

    if re.search(r"\b(?:last|previous)\s+weekday\b", normalized):
        candidate = reference_date - timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return DateScopeResolution(candidate.isoformat(), DateNormalizationMethod.WEEKDAY)
    if re.search(r"\bnext\s+weekday\b", normalized):
        candidate = reference_date + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return DateScopeResolution(candidate.isoformat(), DateNormalizationMethod.WEEKDAY)
    if re.search(r"\bthis\s+weekday\b", normalized):
        candidate = reference_date
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return DateScopeResolution(candidate.isoformat(), DateNormalizationMethod.WEEKDAY)

    weekday_period = re.search(
        r"\b(?:(this|next|last)\s+(?:week(?:'s)?\s+)?)?weekdays\b",
        normalized,
    )
    if weekday_period is not None:
        modifier = weekday_period.group(1)
        offset = 1 if modifier == "next" else -1 if modifier == "last" else 0
        monday = _week_start(reference_date, offset)
        return DateScopeResolution(
            _date_range(monday, monday + timedelta(days=4)),
            DateNormalizationMethod.WEEKDAY_PERIOD,
        )

    weekend_match = re.search(
        r"\b(?:(this|next|last)\s+)?weekends?\b",
        normalized,
    )
    if weekend_match is not None:
        modifier = weekend_match.group(1)
        offset = 1 if modifier == "next" else -1 if modifier == "last" else 0
        saturday = _week_start(reference_date, offset) + timedelta(days=5)
        return DateScopeResolution(
            _date_range(saturday, saturday + timedelta(days=1)),
            DateNormalizationMethod.WEEKEND,
        )

    next_days = re.search(r"\bnext\s+(\d{1,2})\s+days?\b", normalized)
    if next_days is not None:
        days = int(next_days.group(1))
        if days > 0:
            return DateScopeResolution(
                _date_range(reference_date, reference_date + timedelta(days=days)),
                DateNormalizationMethod.RELATIVE_RANGE,
            )

    if re.search(r"\bnext week\b", normalized):
        next_monday = _week_start(reference_date, 1)
        return DateScopeResolution(
            _date_range(next_monday, next_monday + timedelta(days=6)),
            DateNormalizationMethod.RELATIVE_RANGE,
        )
    if re.search(r"\bthis week\b", normalized):
        this_sunday = _week_start(reference_date) + timedelta(days=6)
        return DateScopeResolution(
            _date_range(reference_date, this_sunday),
            DateNormalizationMethod.RELATIVE_RANGE,
        )
    if re.search(r"\bupcoming\b", normalized):
        return DateScopeResolution(
            _date_range(reference_date, reference_date + timedelta(days=7)),
            DateNormalizationMethod.RELATIVE_RANGE,
        )
    return DateScopeResolution(None, DateNormalizationMethod.NONE)


def resolve_date_scope(query: str, reference_date: date) -> str | None:
    """Resolve supported calendar language to one ISO date or inclusive range."""

    return resolve_date_scope_details(query, reference_date).scope
