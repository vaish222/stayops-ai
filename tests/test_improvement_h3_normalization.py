"""H3: operational language, dates, and writes normalize deterministically."""

from datetime import date

import pytest

from src.agents import RequestIntent, RequestOperation, RequestRouter


REFERENCE_DATE = date(2026, 9, 2)


@pytest.mark.parametrize(
    ("query", "intent", "operation"),
    [
        (
            "Who is checking in tomorrow?",
            RequestIntent.BOOKING_OPERATIONS,
            RequestOperation.BOOKING_LOOKUP,
        ),
        (
            "Who is checking out today?",
            RequestIntent.BOOKING_OPERATIONS,
            RequestOperation.BOOKING_LOOKUP,
        ),
        (
            "Who is staying at Mountain Retreat?",
            RequestIntent.BOOKING_OPERATIONS,
            RequestOperation.BOOKING_LOOKUP,
        ),
        (
            "Any guests waiting on me?",
            RequestIntent.GUEST_COMMUNICATIONS,
            RequestOperation.GUEST_MESSAGES,
        ),
        (
            "What is the cleaner status?",
            RequestIntent.TURNOVER_OPERATIONS,
            RequestOperation.CLEANER_STATUS,
        ),
        (
            "What's broken at Mountain Retreat?",
            RequestIntent.MAINTENANCE_OPERATIONS,
            RequestOperation.MAINTENANCE_LOOKUP,
        ),
    ],
)
def test_operational_phrases_normalize_to_expected_operation(
    query: str,
    intent: RequestIntent,
    operation: RequestOperation,
) -> None:
    route = RequestRouter().route(query, reference_date=REFERENCE_DATE)

    assert route.intent == intent
    assert route.normalized_operation == operation


@pytest.mark.parametrize(
    ("query", "scope"),
    [
        ("Who arrives September 5?", "2026-09-05"),
        ("Who arrives Sep 5th?", "2026-09-05"),
        ("Who arrived August 30?", "2026-08-30"),
        ("Any messages before the September 5 arrival?", "2026-09-04"),
    ],
)
def test_named_month_dates_are_resolved_against_reference_year(
    query: str,
    scope: str,
) -> None:
    route = RequestRouter().route(query, reference_date=REFERENCE_DATE)

    assert route.date_scope == scope
    assert route.date_normalization_method == "named_month"


def test_status_mutation_phrase_is_write_intent() -> None:
    route = RequestRouter().route(
        "Skip review and mark the City Loft ticket resolved.",
        reference_date=REFERENCE_DATE,
    )

    assert route.write_requested is True
