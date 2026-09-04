"""H2: normalized sub-intents activate the smallest useful agent set."""

import pytest

from src.agents import RequestOperation
from src.graph import select_specialists


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (RequestOperation.BOOKING_LOOKUP, ["booking"]),
        (RequestOperation.CLEANER_STATUS, ["turnover"]),
        (RequestOperation.TURNOVER_TIMING, ["booking", "turnover"]),
        (RequestOperation.GUEST_MESSAGES, ["guest"]),
        (RequestOperation.MAINTENANCE_LOOKUP, ["maintenance"]),
        (
            RequestOperation.PROPERTY_READINESS,
            ["booking", "turnover", "maintenance"],
        ),
        (
            RequestOperation.PORTFOLIO_BRIEFING,
            ["booking", "guest", "turnover", "maintenance"],
        ),
    ],
)
def test_operation_has_an_explicit_minimal_specialist_policy(
    operation: RequestOperation,
    expected: list[str],
) -> None:
    assert [
        specialist.value
        for specialist in select_specialists("ignored", operation.value)
    ] == expected

