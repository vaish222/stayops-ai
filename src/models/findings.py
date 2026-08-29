"""Pydantic contracts shared by the four specialist agents."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.operations import (
    CleaningSchedule,
    GuestMessage,
    MaintenanceTicket,
    Reservation,
)


class SpecialistName(StrEnum):
    BOOKING = "booking"
    GUEST = "guest"
    TURNOVER = "turnover"
    MAINTENANCE = "maintenance"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(StrEnum):
    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    OCCUPANCY = "occupancy"
    SAME_DAY_TURNOVER = "same_day_turnover"
    RESERVATION_CONFLICT = "reservation_conflict"
    BOOKING_GAP = "booking_gap"
    UNANSWERED_MESSAGE = "unanswered_message"
    EARLY_CHECK_IN_REQUEST = "early_check_in_request"
    GUEST_COMPLAINT = "guest_complaint"
    GUEST_MAINTENANCE_REPORT = "guest_maintenance_report"
    CLEANER_CONFIRMATION_MISSING = "cleaner_confirmation_missing"
    CLEANER_DECLINED = "cleaner_declined"
    TURNOVER_TIMING_RISK = "turnover_timing_risk"
    TURNOVER_ON_TRACK = "turnover_on_track"
    CLEANING_SCHEDULE_MISSING = "cleaning_schedule_missing"
    OPEN_MAINTENANCE = "open_maintenance"
    GUEST_IMPACTING_MAINTENANCE = "guest_impacting_maintenance"
    UPCOMING_STAY_MAINTENANCE_RISK = "upcoming_stay_maintenance_risk"


class EvidenceSource(StrEnum):
    RESERVATIONS = "reservations"
    GUEST_MESSAGES = "guest_messages"
    CLEANING_SCHEDULE = "cleaning_schedule"
    MAINTENANCE_TICKETS = "maintenance_tickets"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingEvidence(StrictModel):
    source: EvidenceSource
    record_ids: list[str] = Field(min_length=1)
    fact: str = Field(min_length=1)

    @field_validator("record_ids")
    @classmethod
    def record_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence record_ids must be unique")
        return values


class SpecialistFinding(StrictModel):
    finding_id: str = Field(min_length=1)
    specialist: SpecialistName
    property_id: str = Field(pattern=r"^prop_[a-z_]+$")
    category: FindingCategory
    severity: FindingSeverity
    summary: str = Field(min_length=1)
    evidence: list[FindingEvidence] = Field(min_length=1)
    recommended_next_action: str | None = None
    requires_attention: bool
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_tool: str = Field(min_length=1)
    retryable: bool


class AgentSourceError(BaseModel):
    """Tool-error shape accepted without coupling domain models to tool code."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    retryable: bool


class SpecialistOutput(StrictModel):
    specialist: SpecialistName
    findings: list[SpecialistFinding]
    analyzed_record_ids: list[str]
    warnings: list[AgentWarning]

    @field_validator("analyzed_record_ids")
    @classmethod
    def analyzed_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("analyzed_record_ids must be unique")
        return values

    @model_validator(mode="after")
    def findings_must_match_specialist(self) -> SpecialistOutput:
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding IDs must be unique")
        if any(finding.specialist != self.specialist for finding in self.findings):
            raise ValueError("every finding must match the output specialist")
        return self


class SpecialistInput(StrictModel):
    property_scope: list[str] = Field(default_factory=list)
    date_scope: str | None = None
    source_errors: list[AgentSourceError] = Field(default_factory=list)

    @field_validator("property_scope")
    @classmethod
    def property_scope_must_be_canonical(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("property_scope cannot contain duplicates")
        if any(not re.fullmatch(r"prop_[a-z_]+", value) for value in values):
            raise ValueError("property_scope must contain canonical property IDs")
        return values

    @field_validator("date_scope")
    @classmethod
    def date_scope_must_be_valid(cls, value: str | None) -> str | None:
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

    def date_bounds(self) -> tuple[date | None, date | None]:
        if self.date_scope is None:
            return None, None
        parts = [date.fromisoformat(part) for part in self.date_scope.split("/")]
        if len(parts) == 1:
            return parts[0], parts[0]
        return parts[0], parts[1]


class BookingAgentInput(SpecialistInput):
    reservations: list[Reservation]


class GuestAgentInput(SpecialistInput):
    guest_messages: list[GuestMessage]


class TurnoverAgentInput(SpecialistInput):
    reservations: list[Reservation]
    cleaning_schedule: list[CleaningSchedule]


class MaintenanceAgentInput(SpecialistInput):
    maintenance_tickets: list[MaintenanceTicket]
    reservations: list[Reservation]
