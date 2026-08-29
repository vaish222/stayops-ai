"""Phase 2 request-router extraction and safety-intent tests."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.agents import RequestIntent, RequestRoute, RequestRouter


REFERENCE_DATE = date(2026, 8, 28)


@pytest.fixture(scope="module")
def router() -> RequestRouter:
    return RequestRouter()


@pytest.mark.parametrize(
    ("query", "intent", "property_scope", "date_scope"),
    [
        (
            "What needs my attention today?",
            RequestIntent.DAILY_BRIEFING,
            [],
            "2026-08-28",
        ),
        (
            "Which guests are arriving at City Loft today?",
            RequestIntent.BOOKING_OPERATIONS,
            ["prop_city_loft"],
            "2026-08-28",
        ),
        (
            "Are all properties ready for today's check-ins?",
            RequestIntent.TURNOVER_OPERATIONS,
            [],
            "2026-08-28",
        ),
        (
            "Are there unresolved guest issues?",
            RequestIntent.GUEST_COMMUNICATIONS,
            [],
            None,
        ),
        (
            "Which maintenance issues could affect upcoming stays at Pine House?",
            RequestIntent.MAINTENANCE_OPERATIONS,
            ["prop_pine_house"],
            "2026-08-28/2026-09-04",
        ),
        (
            "What's the highest-risk property today?",
            RequestIntent.RISK_ASSESSMENT,
            [],
            "2026-08-28",
        ),
    ],
)
def test_router_extracts_read_requests(
    router: RequestRouter,
    query: str,
    intent: RequestIntent,
    property_scope: list[str],
    date_scope: str | None,
) -> None:
    route = router.route(query, reference_date=REFERENCE_DATE)

    assert isinstance(route, RequestRoute)
    assert route.intent == intent
    assert route.property_scope == property_scope
    assert route.date_scope == date_scope
    assert route.write_requested is False


@pytest.mark.parametrize(
    ("query", "intent", "property_scope"),
    [
        (
            "Handle the cleaning issue at Lake House.",
            RequestIntent.TURNOVER_OPERATIONS,
            ["prop_lake_house"],
        ),
        (
            "Send a message to the cleaner at Lake House.",
            RequestIntent.TURNOVER_OPERATIONS,
            ["prop_lake_house"],
        ),
        (
            "Update the maintenance status at Pine House.",
            RequestIntent.MAINTENANCE_OPERATIONS,
            ["prop_pine_house"],
        ),
        (
            "Cancel the reservation for Beach Bungalow.",
            RequestIntent.BOOKING_OPERATIONS,
            ["prop_beach_bungalow"],
        ),
    ],
)
def test_router_flags_write_requests(
    router: RequestRouter,
    query: str,
    intent: RequestIntent,
    property_scope: list[str],
) -> None:
    route = router.route(query, reference_date=REFERENCE_DATE)

    assert route.intent == intent
    assert route.property_scope == property_scope
    assert route.write_requested is True


@pytest.mark.parametrize(
    "query",
    [
        "Which cleaners haven't confirmed?",
        "Show me the guest messages for Beach Bungalow.",
        "Show me today's cleaning schedule.",
        "What reservation changes are pending?",
    ],
)
def test_router_does_not_flag_read_only_wording_as_write(
    router: RequestRouter,
    query: str,
) -> None:
    assert router.route(query, reference_date=REFERENCE_DATE).write_requested is False


def test_router_extracts_multiple_properties_in_query_order(router: RequestRouter) -> None:
    route = router.route(
        "Compare Pine House, Lake House, and City Loft next week.",
        reference_date=REFERENCE_DATE,
    )

    assert route.property_scope == [
        "prop_pine_house",
        "prop_lake_house",
        "prop_city_loft",
    ]
    assert route.date_scope == "2026-08-31/2026-09-06"


def test_schedule_cleaner_is_a_write_request(router: RequestRouter) -> None:
    route = router.route(
        "Schedule a cleaner for Lake House tomorrow.",
        reference_date=REFERENCE_DATE,
    )

    assert route.intent == RequestIntent.TURNOVER_OPERATIONS
    assert route.write_requested is True


def test_router_extracts_explicit_iso_date_range(router: RequestRouter) -> None:
    route = router.route(
        "Show reservations from 2026-09-01 to 2026-09-04.",
        reference_date=REFERENCE_DATE,
    )

    assert route.date_scope == "2026-09-01/2026-09-04"


@pytest.mark.parametrize(
    ("query", "expected_scope"),
    [
        ("What happened yesterday?", "2026-08-27"),
        ("What is happening tomorrow?", "2026-08-29"),
        ("Who arrives Saturday?", "2026-08-29"),
        ("Who arrives next Monday?", "2026-08-31"),
        ("Show operations this weekend.", "2026-08-29/2026-08-30"),
        ("Show operations next weekend.", "2026-09-05/2026-09-06"),
        ("Show operations on weekdays.", "2026-08-24/2026-08-28"),
        ("Show next week's weekdays.", "2026-08-31/2026-09-04"),
        ("Show today's arrivals.", "2026-08-28"),
        ("Show today’s arrivals.", "2026-08-28"),
    ],
)
def test_router_understands_relative_calendar_language(
    router: RequestRouter,
    query: str,
    expected_scope: str,
) -> None:
    assert (
        router.route(query, reference_date=REFERENCE_DATE).date_scope
        == expected_scope
    )


def test_router_rejects_blank_query(router: RequestRouter) -> None:
    with pytest.raises(ValidationError, match="host_query cannot be blank"):
        router.route("   ", reference_date=REFERENCE_DATE)


def test_request_route_rejects_noncanonical_property_id() -> None:
    with pytest.raises(ValidationError, match="canonical property IDs"):
        RequestRoute(
            intent=RequestIntent.GENERAL_OPERATIONS,
            property_scope=["Lake House"],
            date_scope=None,
            write_requested=False,
        )
