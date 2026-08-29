"""Pydantic schemas for the synthetic StayOps operations dataset."""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields so fixture drift fails validation immediately."""

    model_config = ConfigDict(extra="forbid")


class SyntheticRecord(StrictModel):
    """Marks every public fixture row as deliberately fictional."""

    is_synthetic: Literal[True]


class ReservationStatus(StrEnum):
    CONFIRMED = "confirmed"
    IN_HOUSE = "in_house"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageCategory(StrEnum):
    GENERAL = "general"
    CHECK_IN = "check_in"
    EARLY_CHECK_IN = "early_check_in"
    SPECIAL_REQUEST = "special_request"
    COMPLAINT = "complaint"
    MAINTENANCE = "maintenance"


class MessageUrgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    DECLINED = "declined"
    NOT_REQUIRED = "not_required"


class CleaningStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MaintenanceSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MaintenanceStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class Property(SyntheticRecord):
    id: str = Field(pattern=r"^prop_[a-z_]+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    location: str = Field(min_length=1)
    timezone: str
    bedrooms: int = Field(ge=0)
    bathrooms: float = Field(gt=0)
    max_guests: int = Field(gt=0)
    active: bool = True

    @model_validator(mode="after")
    def timezone_must_exist(self) -> Property:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc
        return self


class Reservation(SyntheticRecord):
    id: str = Field(pattern=r"^res_[a-z0-9_]+$")
    property_id: str
    guest_id: str = Field(pattern=r"^guest_[a-z0-9_]+$")
    guest_name: str = Field(min_length=1)
    check_in_date: date
    check_out_date: date
    check_in_time: time
    check_out_time: time
    guest_count: int = Field(gt=0)
    status: ReservationStatus
    source: Literal["direct", "synthetic_marketplace"]
    notes: str | None = None

    @model_validator(mode="after")
    def stay_must_have_positive_length(self) -> Reservation:
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")
        return self


class GuestMessage(SyntheticRecord):
    id: str = Field(pattern=r"^msg_[a-z0-9_]+$")
    property_id: str
    reservation_id: str
    guest_id: str
    guest_name: str = Field(min_length=1)
    received_at: datetime
    direction: MessageDirection
    category: MessageCategory
    urgency: MessageUrgency
    body: str = Field(min_length=1)
    requires_response: bool
    responded_at: datetime | None = None

    @model_validator(mode="after")
    def response_fields_must_be_consistent(self) -> GuestMessage:
        if self.direction == MessageDirection.OUTBOUND and self.responded_at is not None:
            raise ValueError("outbound messages cannot have responded_at")
        if self.responded_at is not None and self.responded_at < self.received_at:
            raise ValueError("responded_at cannot precede received_at")
        return self


class CleaningSchedule(SyntheticRecord):
    id: str = Field(pattern=r"^clean_[a-z0-9_]+$")
    property_id: str
    checkout_reservation_id: str | None = None
    next_reservation_id: str | None = None
    scheduled_date: date
    window_start: time
    target_complete_time: time
    cleaner_id: str = Field(pattern=r"^cleaner_[a-z0-9_]+$")
    cleaner_name: str = Field(min_length=1)
    confirmation_status: ConfirmationStatus
    status: CleaningStatus
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def schedule_fields_must_be_consistent(self) -> CleaningSchedule:
        if self.target_complete_time <= self.window_start:
            raise ValueError("target_complete_time must be after window_start")
        if self.confirmation_status == ConfirmationStatus.CONFIRMED:
            if self.confirmed_at is None:
                raise ValueError("confirmed cleaning must include confirmed_at")
        elif self.confirmed_at is not None:
            raise ValueError("only confirmed cleaning may include confirmed_at")
        if self.status == CleaningStatus.COMPLETED:
            if self.completed_at is None:
                raise ValueError("completed cleaning must include completed_at")
        elif self.completed_at is not None:
            raise ValueError("only completed cleaning may include completed_at")
        return self


class MaintenanceTicket(SyntheticRecord):
    id: str = Field(pattern=r"^maint_[a-z0-9_]+$")
    property_id: str
    reservation_id: str | None = None
    reported_by: Literal["guest", "host", "cleaner", "inspection"]
    summary: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: MaintenanceSeverity
    status: MaintenanceStatus
    guest_impact: bool
    blocks_checkin: bool
    created_at: datetime
    updated_at: datetime
    assigned_vendor: str | None = None
    resolution_notes: str | None = None

    @model_validator(mode="after")
    def ticket_fields_must_be_consistent(self) -> MaintenanceTicket:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.status == MaintenanceStatus.RESOLVED and not self.resolution_notes:
            raise ValueError("resolved ticket must include resolution_notes")
        if self.status != MaintenanceStatus.RESOLVED and self.resolution_notes:
            raise ValueError("unresolved ticket cannot include resolution_notes")
        return self


class PropertyRule(SyntheticRecord):
    id: str = Field(pattern=r"^rule_[a-z_]+$")
    property_id: str
    standard_check_in_time: time
    standard_check_out_time: time
    quiet_hours_start: time
    quiet_hours_end: time
    early_check_in_policy: Literal["not_allowed", "host_approval", "when_ready"]
    pets_policy: Literal["not_allowed", "allowed", "host_approval"]
    smoking_allowed: Literal[False]
    max_occupancy: int = Field(gt=0)
    parking_instructions: str = Field(min_length=1)
    cleaner_ready_buffer_minutes: int = Field(ge=0, le=360)
    house_rules: list[str] = Field(min_length=1)


class StayOpsDataset(StrictModel):
    """The complete fixture set, including cross-file relationship checks."""

    properties: list[Property]
    reservations: list[Reservation]
    guest_messages: list[GuestMessage]
    cleaning_schedule: list[CleaningSchedule]
    maintenance_tickets: list[MaintenanceTicket]
    property_rules: list[PropertyRule]

    @staticmethod
    def _index_unique(records: list[SyntheticRecord], label: str) -> dict[str, SyntheticRecord]:
        indexed = {record.id: record for record in records}  # type: ignore[attr-defined]
        if len(indexed) != len(records):
            raise ValueError(f"{label} contains duplicate IDs")
        return indexed

    @model_validator(mode="after")
    def relationships_must_be_valid(self) -> StayOpsDataset:
        properties = self._index_unique(self.properties, "properties")
        reservations = self._index_unique(self.reservations, "reservations")
        self._index_unique(self.guest_messages, "guest_messages")
        self._index_unique(self.cleaning_schedule, "cleaning_schedule")
        self._index_unique(self.maintenance_tickets, "maintenance_tickets")
        rules = self._index_unique(self.property_rules, "property_rules")

        property_ids = set(properties)
        rule_property_ids = {rule.property_id for rule in rules.values()}
        if rule_property_ids != property_ids:
            raise ValueError("property_rules must contain exactly one rule for every property")
        if len(rule_property_ids) != len(rules):
            raise ValueError("a property cannot have multiple property_rules")

        for reservation in reservations.values():
            if reservation.property_id not in property_ids:
                raise ValueError(f"{reservation.id} references an unknown property")
            prop = properties[reservation.property_id]
            if reservation.guest_count > prop.max_guests:
                raise ValueError(f"{reservation.id} exceeds property capacity")

        for message in self.guest_messages:
            reservation = reservations.get(message.reservation_id)
            if reservation is None:
                raise ValueError(f"{message.id} references an unknown reservation")
            if message.property_id != reservation.property_id:
                raise ValueError(f"{message.id} does not match its reservation property")
            if (message.guest_id, message.guest_name) != (
                reservation.guest_id,
                reservation.guest_name,
            ):
                raise ValueError(f"{message.id} does not match its reservation guest")

        for cleaning in self.cleaning_schedule:
            if cleaning.property_id not in property_ids:
                raise ValueError(f"{cleaning.id} references an unknown property")
            if cleaning.checkout_reservation_id is not None:
                checkout = reservations.get(cleaning.checkout_reservation_id)
                if checkout is None or checkout.property_id != cleaning.property_id:
                    raise ValueError(f"{cleaning.id} has an invalid checkout reservation")
                if checkout.check_out_date != cleaning.scheduled_date:
                    raise ValueError(f"{cleaning.id} is not scheduled on checkout date")
            if cleaning.next_reservation_id is not None:
                upcoming = reservations.get(cleaning.next_reservation_id)
                if upcoming is None or upcoming.property_id != cleaning.property_id:
                    raise ValueError(f"{cleaning.id} has an invalid next reservation")
                if upcoming.check_in_date != cleaning.scheduled_date:
                    raise ValueError(f"{cleaning.id} is not scheduled on next check-in date")

        for ticket in self.maintenance_tickets:
            if ticket.property_id not in property_ids:
                raise ValueError(f"{ticket.id} references an unknown property")
            if ticket.reservation_id is not None:
                reservation = reservations.get(ticket.reservation_id)
                if reservation is None or reservation.property_id != ticket.property_id:
                    raise ValueError(f"{ticket.id} has an invalid reservation")

        for rule in rules.values():
            prop = properties[rule.property_id]
            if rule.max_occupancy != prop.max_guests:
                raise ValueError(f"{rule.id} occupancy does not match its property")

        active = [r for r in reservations.values() if r.status != ReservationStatus.CANCELLED]
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                if left.property_id != right.property_id:
                    continue
                overlaps = (
                    left.check_in_date < right.check_out_date
                    and right.check_in_date < left.check_out_date
                )
                if overlaps:
                    raise ValueError(f"reservations {left.id} and {right.id} overlap")

        return self
