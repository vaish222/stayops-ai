"""Deterministic Pydantic request routing for host queries."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agents.request_operation import RequestOperation, classify_request_operation
from src.time_context import (
    DateNormalizationMethod,
    current_operating_date,
    resolve_date_scope_details,
)


class RequestIntent(StrEnum):
    DAILY_BRIEFING = "daily_briefing"
    BOOKING_OPERATIONS = "booking_operations"
    GUEST_COMMUNICATIONS = "guest_communications"
    TURNOVER_OPERATIONS = "turnover_operations"
    MAINTENANCE_OPERATIONS = "maintenance_operations"
    RISK_ASSESSMENT = "risk_assessment"
    GENERAL_OPERATIONS = "general_operations"


class RouterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_query: str = Field(min_length=1)

    @field_validator("host_query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("host_query cannot be blank")
        return normalized


class RequestRoute(BaseModel):
    """Validated fields written by the request-router graph node."""

    model_config = ConfigDict(extra="forbid")

    intent: RequestIntent
    property_scope: list[str]
    date_scope: str | None
    write_requested: bool
    normalized_operation: RequestOperation = RequestOperation.GENERAL
    readiness_detected: bool = False
    date_normalization_method: DateNormalizationMethod = DateNormalizationMethod.NONE

    @field_validator("property_scope")
    @classmethod
    def property_scope_must_be_canonical(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("property_scope cannot contain duplicate IDs")
        if any(not re.fullmatch(r"prop_[a-z_]+", value) for value in values):
            raise ValueError("property_scope must contain canonical property IDs")
        return values

    @field_validator("date_scope")
    @classmethod
    def date_scope_must_be_iso_date_or_range(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if len(parts) not in (1, 2):
            raise ValueError("date_scope must be an ISO date or inclusive ISO range")
        try:
            parsed = [date.fromisoformat(part) for part in parts]
        except ValueError as exc:
            raise ValueError("date_scope must contain valid ISO dates") from exc
        if len(parsed) == 2 and parsed[0] > parsed[1]:
            raise ValueError("date_scope range cannot be reversed")
        return value


DEFAULT_PROPERTY_NAMES: dict[str, str] = {
    "lake house": "prop_lake_house",
    "pine house": "prop_pine_house",
    "city loft": "prop_city_loft",
    "garden cottage": "prop_garden_cottage",
    "sunset house": "prop_sunset_house",
    "beach bungalow": "prop_beach_bungalow",
    "mountain retreat": "prop_mountain_retreat",
    "downtown suite": "prop_downtown_suite",
}


INTENT_PATTERNS: tuple[tuple[RequestIntent, tuple[str, ...]], ...] = (
    (
        RequestIntent.RISK_ASSESSMENT,
        (r"\bhighest[- ]risk\b", r"\bmost at risk\b", r"\brisk(?:y|s)?\b"),
    ),
    (
        RequestIntent.MAINTENANCE_OPERATIONS,
        (
            r"\bmaintenance\b",
            r"\brepair(?:s|ed)?\b",
            r"\b(?:broken|leak|plumbing|outage|air conditioner|\bac\b|hvac)\b",
            r"\bwork order\b",
        ),
    ),
    (
        RequestIntent.TURNOVER_OPERATIONS,
        (
            r"\bclean(?:er|ers|ing)?\b",
            r"\bturnover(?:s)?\b",
            r"\bread(?:y|iness)\b",
        ),
    ),
    (
        RequestIntent.GUEST_COMMUNICATIONS,
        (
            r"\bguest (?:message|messages|issue|issues|request|requests|complaint|complaints)\b",
            r"\bunanswered\b",
            r"\bearly check[- ]in\b",
            r"\bcomplaint(?:s)?\b",
        ),
    ),
    (
        RequestIntent.BOOKING_OPERATIONS,
        (
            r"\barriv(?:al|als|e|es|ing)\b",
            r"\bdepart(?:ure|ures|ing|s)?\b",
            r"\bbooking(?:s)?\b",
            r"\breservation(?:s)?\b",
            r"\boccupancy\b",
            r"\bcheck[- ](?:in|out)s?\b",
            r"\bvacan(?:t|cy)\b",
        ),
    ),
)


WRITE_PATTERNS: tuple[str, ...] = (
    r"\b(?:send|contact|notify|call|text)\b",
    r"\b(?:message|email)\s+(?:the\s+)?(?:guest|cleaner|vendor|owner|host)\b",
    r"\b(?:reply|respond)\s+to\b",
    r"\b(?:modify|change|cancel|update|assign|reschedule)\b",
    r"\bschedule\s+(?:a\s+|an\s+|the\s+)?(?:cleaner|cleaning|repair|visit|turnover)\b",
    r"\b(?:approve|reject)\b",
    (
        r"\b(?:handle|fix|resolve|close|reopen)\b.{0,40}"
        r"\b(?:issue|ticket|problem|cleaning|reservation)\b"
    ),
    r"\b(?:fix|repair)\s+(?:the\s+)?(?:ac|air conditioner|hvac|leak|plumbing|appliance)\b",
    r"\bmark\b.{0,50}\b(?:resolved|closed|open|in[-_ ]progress|complete(?:d)?)\b",
    r"\bset\b.{0,50}\bstatus\s+to\b",
)


class RequestRouter:
    """Extract a validated route without calling an LLM or operational tool."""

    def __init__(self, property_names: dict[str, str] | None = None) -> None:
        names = DEFAULT_PROPERTY_NAMES if property_names is None else property_names
        self._property_names = {name.casefold(): property_id for name, property_id in names.items()}

    def route(
        self,
        host_query: str,
        *,
        reference_date: date | None = None,
    ) -> RequestRoute:
        router_input = RouterInput(host_query=host_query)
        normalized_query = router_input.host_query.casefold()
        today = reference_date or current_operating_date()
        operation = classify_request_operation(normalized_query)
        date_resolution = resolve_date_scope_details(normalized_query, today)

        return RequestRoute(
            intent=self._extract_intent(normalized_query, operation),
            property_scope=self._extract_property_scope(normalized_query),
            date_scope=date_resolution.scope,
            write_requested=self._extract_write_requested(normalized_query),
            normalized_operation=operation,
            readiness_detected=operation == RequestOperation.PROPERTY_READINESS,
            date_normalization_method=date_resolution.method,
        )

    def _extract_property_scope(self, query: str) -> list[str]:
        matches: list[tuple[int, str]] = []
        for name, property_id in self._property_names.items():
            match = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", query)
            if match is not None:
                matches.append((match.start(), property_id))
        return [property_id for _, property_id in sorted(matches)]

    @staticmethod
    def _extract_intent(
        query: str,
        operation: RequestOperation | None = None,
    ) -> RequestIntent:
        resolved_operation = operation or classify_request_operation(query)
        if (
            resolved_operation == RequestOperation.PROPERTY_READINESS
            and re.search(r"\b(?:good for|good to go)\b", query)
        ):
            return RequestIntent.RISK_ASSESSMENT
        if (
            resolved_operation == RequestOperation.TURNOVER_TIMING
            and re.search(r"\banything\b.{0,40}\bhandle\b", query)
        ):
            return RequestIntent.GENERAL_OPERATIONS
        operation_intents = {
            RequestOperation.BOOKING_LOOKUP: RequestIntent.BOOKING_OPERATIONS,
            RequestOperation.GUEST_MESSAGES: RequestIntent.GUEST_COMMUNICATIONS,
            RequestOperation.CLEANER_STATUS: RequestIntent.TURNOVER_OPERATIONS,
            RequestOperation.TURNOVER_TIMING: RequestIntent.TURNOVER_OPERATIONS,
            RequestOperation.MAINTENANCE_LOOKUP: RequestIntent.MAINTENANCE_OPERATIONS,
            RequestOperation.PROPERTY_READINESS: RequestIntent.TURNOVER_OPERATIONS,
            RequestOperation.PORTFOLIO_BRIEFING: RequestIntent.DAILY_BRIEFING,
            RequestOperation.BROAD_RISK: RequestIntent.RISK_ASSESSMENT,
        }
        if resolved_operation in operation_intents:
            return operation_intents[resolved_operation]
        for intent, patterns in INTENT_PATTERNS:
            if any(re.search(pattern, query) for pattern in patterns):
                return intent
        if re.search(r"\b(?:attention|briefing|overview|status|priorities)\b", query):
            return RequestIntent.DAILY_BRIEFING
        return RequestIntent.GENERAL_OPERATIONS

    @staticmethod
    def _extract_write_requested(query: str) -> bool:
        return any(re.search(pattern, query) for pattern in WRITE_PATTERNS)
