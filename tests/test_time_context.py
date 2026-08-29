"""Operating timezone and calendar-scope unit tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.time_context import current_operating_date, resolve_date_scope


def test_operating_date_uses_local_calendar_day_not_utc_day() -> None:
    utc_now = datetime(2026, 8, 29, 6, 30, tzinfo=timezone.utc)

    assert current_operating_date(utc_now) == date(2026, 8, 28)


def test_next_weekday_skips_the_weekend() -> None:
    assert resolve_date_scope("Show the next weekday", date(2026, 8, 28)) == (
        "2026-08-31"
    )


def test_previous_weekday_skips_the_weekend() -> None:
    assert resolve_date_scope("Show the previous weekday", date(2026, 8, 31)) == (
        "2026-08-28"
    )
