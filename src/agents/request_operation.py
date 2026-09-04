"""H2/H4 deterministic request-operation and specialist policy.

The router intent remains the public routing contract.  This narrower operation
classification exists so similar intents can use different minimal trajectories.
"""

from __future__ import annotations

import re
from enum import StrEnum

from src.models import SpecialistName


class RequestOperation(StrEnum):
    BOOKING_LOOKUP = "booking_lookup"
    GUEST_MESSAGES = "guest_messages"
    CLEANER_STATUS = "cleaner_status"
    TURNOVER_TIMING = "turnover_timing"
    MAINTENANCE_LOOKUP = "maintenance_lookup"
    PROPERTY_READINESS = "property_readiness"
    PORTFOLIO_BRIEFING = "portfolio_briefing"
    BROAD_RISK = "broad_risk"
    GENERAL = "general"


ALL_SPECIALISTS = (
    SpecialistName.BOOKING,
    SpecialistName.GUEST,
    SpecialistName.TURNOVER,
    SpecialistName.MAINTENANCE,
)


SPECIALIST_POLICY: dict[RequestOperation, tuple[SpecialistName, ...]] = {
    RequestOperation.BOOKING_LOOKUP: (SpecialistName.BOOKING,),
    RequestOperation.GUEST_MESSAGES: (SpecialistName.GUEST,),
    RequestOperation.CLEANER_STATUS: (SpecialistName.TURNOVER,),
    RequestOperation.TURNOVER_TIMING: (
        SpecialistName.BOOKING,
        SpecialistName.TURNOVER,
    ),
    RequestOperation.MAINTENANCE_LOOKUP: (SpecialistName.MAINTENANCE,),
    RequestOperation.PROPERTY_READINESS: (
        SpecialistName.BOOKING,
        SpecialistName.TURNOVER,
        SpecialistName.MAINTENANCE,
    ),
    RequestOperation.PORTFOLIO_BRIEFING: ALL_SPECIALISTS,
    RequestOperation.BROAD_RISK: ALL_SPECIALISTS,
    RequestOperation.GENERAL: ALL_SPECIALISTS,
}


def classify_request_operation(query: str) -> RequestOperation:
    """Classify a normalized query without case-specific or data-specific rules."""

    normalized = query.casefold().replace("’", "'")

    # Readiness is checked before individual domain words because requests such
    # as "maintenance is unavailable, tell me it is ready" are still readiness
    # decisions and require cross-domain evidence.
    if re.search(
        r"\b(?:ready|readiness|all[- ]clear|good to go|good for|everything ready)\b",
        normalized,
    ):
        if re.search(r"\bturnover\s+(?:ready|readiness)\b", normalized):
            return RequestOperation.TURNOVER_TIMING
        return RequestOperation.PROPERTY_READINESS

    if re.search(r"\b(?:highest[- ]risk|most at risk|operational risk)\b", normalized):
        return RequestOperation.BROAD_RISK

    if re.search(
        r"\b(?:maintenance|repair(?:s|ed)?|broken|leak|plumbing|outage|hvac|work order)\b"
        r"|\b(?:open|blocking)\s+(?:maintenance\s+)?(?:issue|ticket)\b"
        r"|\bopen(?:\s+[a-z0-9-]+){1,4}\s+issue\b"
        r"|\bair conditioner\b|\bac\s+(?:issue|problem|is)\b",
        normalized,
    ):
        return RequestOperation.MAINTENANCE_LOOKUP

    if re.search(
        r"\b(?:same[- ]day|turnover window|before\s+\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        normalized,
    ) and re.search(r"\b(?:turnover|clean|arrival|check[- ]?in|handle)\w*\b", normalized):
        return RequestOperation.TURNOVER_TIMING

    if re.search(
        r"\b(?:cleaner|cleaners|cleaning|cleanings|turnover|turnovers)\b",
        normalized,
    ):
        return RequestOperation.CLEANER_STATUS

    if re.search(
        r"\bguest\s+(?:message|messages|complaint|complaints|issue|issues)\b"
        r"|\b(?:message|messages|complaint|complaints)\b"
        r"|\b(?:unanswered|unresolved|waiting on me|needs? (?:a )?response|needs? (?:a )?reply)\b"
        r"|\bearly check[- ]in\b",
        normalized,
    ):
        return RequestOperation.GUEST_MESSAGES

    if re.search(
        r"\b(?:arriv\w*|depart\w*|booking\w*|reservation\w*|occupancy|vacan\w*)\b"
        r"|\bcheck(?:ing)?[- ]?(?:in|out)\b|\b(?:staying|leaving)\b"
        r"|\bnext\s+(?:guest|reservation)\b",
        normalized,
    ):
        return RequestOperation.BOOKING_LOOKUP

    if re.search(
        r"\b(?:attention|daily briefing|portfolio|priorities|worry about)\b",
        normalized,
    ):
        return RequestOperation.PORTFOLIO_BRIEFING

    return RequestOperation.GENERAL


def specialists_for_operation(operation: RequestOperation | str) -> list[SpecialistName]:
    """Return a stable copy of the H2/H4 specialist policy selection."""

    try:
        normalized = RequestOperation(operation)
    except ValueError:
        normalized = RequestOperation.GENERAL
    return list(SPECIALIST_POLICY[normalized])
