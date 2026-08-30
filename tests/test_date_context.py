"""Tests for operator-facing date-context presentation helpers."""

from __future__ import annotations

from datetime import date

from src.ui import (
    format_answer_date_context,
    format_date_context,
    format_scope_context,
    operations_copy,
    parse_date_scope,
    readiness_copy,
    single_date_from_scope,
)


TODAY = date(2026, 8, 29)


def test_nearby_dates_use_relative_and_calendar_labels() -> None:
    assert format_date_context(TODAY, TODAY) == "Today · Aug 29"
    assert format_date_context(date(2026, 8, 30), TODAY) == "Tomorrow · Aug 30"
    assert format_date_context(date(2026, 8, 28), TODAY) == "Yesterday · Aug 28"
    assert format_date_context(date(2027, 1, 4), TODAY) == "Jan 4, 2027"


def test_structured_date_scopes_support_single_dates_and_ranges() -> None:
    assert parse_date_scope("2026-08-29") == (TODAY, TODAY)
    assert single_date_from_scope("2026-08-29") == TODAY
    assert single_date_from_scope("2026-08-29/2026-08-31") is None
    assert format_scope_context("2026-08-29/2026-08-31", TODAY) == "Aug 29–31"
    assert parse_date_scope("not-a-date") is None


def test_answer_context_distinguishes_past_present_and_future() -> None:
    assert format_answer_date_context("2026-08-29", TODAY) == "For Today · Aug 29"
    assert format_answer_date_context("2026-08-30", TODAY) == (
        "Looking ahead to Tomorrow · Aug 30"
    )
    assert format_answer_date_context("2026-08-28", TODAY) == (
        "Looking back to Yesterday · Aug 28"
    )
    assert format_answer_date_context(None, TODAY) == "For the requested period"


def test_section_copy_tracks_the_selected_dashboard_date() -> None:
    assert readiness_copy(TODAY, TODAY, 8) == (
        "Today's readiness across all 8 properties."
    )
    assert readiness_copy(date(2026, 8, 30), TODAY, 8) == (
        "Tomorrow's readiness across all 8 properties."
    )
    assert operations_copy(date(2026, 8, 28), TODAY) == "Yesterday's operations"
