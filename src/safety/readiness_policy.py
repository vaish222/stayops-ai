"""H4 deterministic completeness rules for property-readiness answers."""

from __future__ import annotations

from src.agents.request_operation import RequestOperation
from src.models import OverallStatus


READINESS_REQUIRED_SOURCES = frozenset(
    {
        "get_reservations",
        "get_cleaning_schedule",
        "get_maintenance_tickets",
    }
)


def enforce_readiness_status(
    *,
    normalized_operation: str,
    unavailable_sources: list[str],
    overall_status: str,
) -> str:
    """Prevent an all-clear when required readiness evidence is unavailable."""

    if normalized_operation != RequestOperation.PROPERTY_READINESS.value:
        return overall_status
    if READINESS_REQUIRED_SOURCES.intersection(unavailable_sources):
        return OverallStatus.NEEDS_ATTENTION.value
    return overall_status

