"""Booking specialist for arrivals, departures, occupancy, conflicts, and gaps."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.agents.base import BaseSpecialistAgent, date_in_scope, property_in_scope
from src.models import (
    BookingAgentInput,
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    Reservation,
    ReservationStatus,
    SpecialistFinding,
    SpecialistName,
    SpecialistOutput,
)
from src.tools import ReadToolName


class BookingAgent(BaseSpecialistAgent[BookingAgentInput]):
    input_model = BookingAgentInput
    specialist = SpecialistName.BOOKING

    def analyze(self, context: BookingAgentInput) -> SpecialistOutput:
        if ReadToolName.GET_RESERVATIONS.value in self.failed_source_tools(context):
            return self.build_output(context, [], [])

        start, end = context.date_bounds()
        reservations = [
            reservation
            for reservation in context.reservations
            if reservation.status != ReservationStatus.CANCELLED
            and property_in_scope(reservation.property_id, context.property_scope)
            and (start is None or reservation.check_out_date >= start)
            and (end is None or reservation.check_in_date <= end)
        ]
        findings: list[SpecialistFinding] = []

        for reservation in reservations:
            if date_in_scope(reservation.check_in_date, start, end):
                findings.append(
                    self._reservation_event_finding(
                        reservation.id,
                        reservation.property_id,
                        FindingCategory.ARRIVAL,
                        reservation.check_in_date,
                        f"Arrival is scheduled at {reservation.check_in_time.strftime('%H:%M')}.",
                    )
                )
            if date_in_scope(reservation.check_out_date, start, end):
                findings.append(
                    self._reservation_event_finding(
                        reservation.id,
                        reservation.property_id,
                        FindingCategory.DEPARTURE,
                        reservation.check_out_date,
                        f"Departure is scheduled at {reservation.check_out_time.strftime('%H:%M')}.",
                    )
                )

        if start is not None and start == end:
            for reservation in reservations:
                if reservation.check_in_date <= start < reservation.check_out_date:
                    findings.append(
                        SpecialistFinding(
                            finding_id=f"booking:occupancy:{reservation.id}:{start.isoformat()}",
                            specialist=self.specialist,
                            property_id=reservation.property_id,
                            category=FindingCategory.OCCUPANCY,
                            severity=FindingSeverity.LOW,
                            summary=f"Property is occupied on {start.isoformat()}.",
                            evidence=[
                                FindingEvidence(
                                    source=EvidenceSource.RESERVATIONS,
                                    record_ids=[reservation.id],
                                    fact=(
                                        f"Reservation runs from {reservation.check_in_date.isoformat()} "
                                        f"through {reservation.check_out_date.isoformat()}."
                                    ),
                                )
                            ],
                            recommended_next_action=None,
                            requires_attention=False,
                        )
                    )

        by_property: dict[str, list[Reservation]] = defaultdict(list)
        for reservation in reservations:
            by_property[reservation.property_id].append(reservation)

        for property_id, property_reservations in by_property.items():
            ordered = sorted(
                property_reservations,
                key=lambda item: (item.check_in_date, item.check_out_date, item.id),
            )
            findings.extend(self._pair_findings(property_id, ordered, start, end))

        return self.build_output(
            context,
            findings,
            [reservation.id for reservation in reservations],
        )

    def _reservation_event_finding(
        self,
        reservation_id: str,
        property_id: str,
        category: FindingCategory,
        event_date: date,
        fact: str,
    ) -> SpecialistFinding:
        label = "Arrival" if category == FindingCategory.ARRIVAL else "Departure"
        return SpecialistFinding(
            finding_id=f"booking:{category.value}:{reservation_id}",
            specialist=self.specialist,
            property_id=property_id,
            category=category,
            severity=FindingSeverity.LOW,
            summary=f"{label} scheduled for {event_date.isoformat()}.",
            evidence=[
                FindingEvidence(
                    source=EvidenceSource.RESERVATIONS,
                    record_ids=[reservation_id],
                    fact=fact,
                )
            ],
            recommended_next_action=None,
            requires_attention=False,
        )

    def _pair_findings(
        self,
        property_id: str,
        reservations: list[Reservation],
        start: date | None,
        end: date | None,
    ) -> list[SpecialistFinding]:
        findings: list[SpecialistFinding] = []
        for index, left in enumerate(reservations):
            for right in reservations[index + 1 :]:
                overlaps = (
                    left.check_in_date < right.check_out_date
                    and right.check_in_date < left.check_out_date
                )
                if overlaps:
                    findings.append(
                        SpecialistFinding(
                            finding_id=f"booking:conflict:{left.id}:{right.id}",
                            specialist=self.specialist,
                            property_id=property_id,
                            category=FindingCategory.RESERVATION_CONFLICT,
                            severity=FindingSeverity.CRITICAL,
                            summary="Two reservations have overlapping stay dates.",
                            evidence=[
                                FindingEvidence(
                                    source=EvidenceSource.RESERVATIONS,
                                    record_ids=[left.id, right.id],
                                    fact=(
                                        f"{left.id} is {left.check_in_date.isoformat()} to "
                                        f"{left.check_out_date.isoformat()}; {right.id} is "
                                        f"{right.check_in_date.isoformat()} to "
                                        f"{right.check_out_date.isoformat()}."
                                    ),
                                )
                            ],
                            recommended_next_action="Host should review the conflicting reservations.",
                            requires_attention=True,
                        )
                    )

            if index + 1 >= len(reservations):
                continue
            right = reservations[index + 1]
            if left.check_out_date == right.check_in_date and date_in_scope(
                right.check_in_date, start, end
            ):
                findings.append(
                    SpecialistFinding(
                        finding_id=f"booking:same_day:{property_id}:{right.check_in_date.isoformat()}",
                        specialist=self.specialist,
                        property_id=property_id,
                        category=FindingCategory.SAME_DAY_TURNOVER,
                        severity=FindingSeverity.MEDIUM,
                        summary=f"Same-day departure and arrival on {right.check_in_date.isoformat()}.",
                        evidence=[
                            FindingEvidence(
                                source=EvidenceSource.RESERVATIONS,
                                record_ids=[left.id, right.id],
                                fact=(
                                    f"{left.id} checks out at {left.check_out_time.strftime('%H:%M')} "
                                    f"and {right.id} checks in at {right.check_in_time.strftime('%H:%M')}."
                                ),
                            )
                        ],
                        recommended_next_action="Verify turnover readiness between the two stays.",
                        requires_attention=True,
                    )
                )
            elif left.check_out_date < right.check_in_date:
                gap_days = (right.check_in_date - left.check_out_date).days
                gap_in_scope = (
                    (start is None or right.check_in_date >= start)
                    and (end is None or left.check_out_date <= end)
                )
                if gap_in_scope:
                    findings.append(
                        SpecialistFinding(
                            finding_id=f"booking:gap:{left.id}:{right.id}",
                            specialist=self.specialist,
                            property_id=property_id,
                            category=FindingCategory.BOOKING_GAP,
                            severity=FindingSeverity.LOW,
                            summary=f"There is a {gap_days}-night booking gap.",
                            evidence=[
                                FindingEvidence(
                                    source=EvidenceSource.RESERVATIONS,
                                    record_ids=[left.id, right.id],
                                    fact=(
                                        f"The prior stay ends {left.check_out_date.isoformat()} and "
                                        f"the next stay begins {right.check_in_date.isoformat()}."
                                    ),
                                )
                            ],
                            recommended_next_action=None,
                            requires_attention=False,
                        )
                    )
        return findings
