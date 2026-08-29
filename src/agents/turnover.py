"""Turnover specialist for cleaner confirmation and check-in readiness risk."""

from __future__ import annotations

from datetime import date, timedelta

from src.agents.base import BaseSpecialistAgent, date_in_scope, property_in_scope
from src.models import (
    CleaningSchedule,
    CleaningStatus,
    ConfirmationStatus,
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    Reservation,
    ReservationStatus,
    SpecialistFinding,
    SpecialistName,
    SpecialistOutput,
    TurnoverAgentInput,
)
from src.tools import ReadToolName


class TurnoverAgent(BaseSpecialistAgent[TurnoverAgentInput]):
    input_model = TurnoverAgentInput
    specialist = SpecialistName.TURNOVER

    def analyze(self, context: TurnoverAgentInput) -> SpecialistOutput:
        failed_tools = self.failed_source_tools(context)
        reservations_failed = ReadToolName.GET_RESERVATIONS.value in failed_tools
        cleaning_failed = ReadToolName.GET_CLEANING_SCHEDULE.value in failed_tools
        if cleaning_failed:
            return self.build_output(context, [], [])

        start, end = context.date_bounds()
        cleanings = [
            cleaning
            for cleaning in context.cleaning_schedule
            if property_in_scope(cleaning.property_id, context.property_scope)
            and date_in_scope(cleaning.scheduled_date, start, end)
        ]
        reservations = (
            [
                reservation
                for reservation in context.reservations
                if property_in_scope(reservation.property_id, context.property_scope)
            ]
            if not reservations_failed
            else []
        )
        reservations_by_id = {reservation.id: reservation for reservation in reservations}
        findings: list[SpecialistFinding] = []

        for cleaning in cleanings:
            next_reservation = (
                reservations_by_id.get(cleaning.next_reservation_id)
                if cleaning.next_reservation_id
                else None
            )
            checkout_reservation = (
                reservations_by_id.get(cleaning.checkout_reservation_id)
                if cleaning.checkout_reservation_id
                else None
            )
            schedule_evidence = FindingEvidence(
                source=EvidenceSource.CLEANING_SCHEDULE,
                record_ids=[cleaning.id],
                fact=(
                    f"Cleaning {cleaning.id} is scheduled for "
                    f"{cleaning.scheduled_date.isoformat()} and has confirmation status "
                    f"{cleaning.confirmation_status.value}."
                ),
            )
            reservation_evidence = []
            linked_reservation_ids = [
                reservation.id
                for reservation in (checkout_reservation, next_reservation)
                if reservation is not None
            ]
            if linked_reservation_ids:
                linked_facts = []
                if checkout_reservation is not None:
                    linked_facts.append(
                        f"{checkout_reservation.id} checks out on "
                        f"{checkout_reservation.check_out_date.isoformat()} at "
                        f"{checkout_reservation.check_out_time.strftime('%H:%M')}"
                    )
                if next_reservation is not None:
                    linked_facts.append(
                        f"{next_reservation.id} checks in on "
                        f"{next_reservation.check_in_date.isoformat()} at "
                        f"{next_reservation.check_in_time.strftime('%H:%M')}"
                    )
                reservation_evidence.append(
                    FindingEvidence(
                        source=EvidenceSource.RESERVATIONS,
                        record_ids=linked_reservation_ids,
                        fact="; ".join(linked_facts) + ".",
                    )
                )

            if cleaning.confirmation_status == ConfirmationStatus.PENDING:
                same_day = (
                    checkout_reservation is not None
                    and next_reservation is not None
                    and checkout_reservation.check_out_date
                    == next_reservation.check_in_date
                    == cleaning.scheduled_date
                )
                findings.append(
                    SpecialistFinding(
                        finding_id=f"turnover:confirmation_missing:{cleaning.id}",
                        specialist=self.specialist,
                        property_id=cleaning.property_id,
                        category=FindingCategory.CLEANER_CONFIRMATION_MISSING,
                        severity=(
                            FindingSeverity.HIGH if same_day else FindingSeverity.MEDIUM
                        ),
                        summary=(
                            "Cleaner confirmation is missing for a same-day turnover."
                            if same_day
                            else "Cleaner confirmation is missing."
                        ),
                        evidence=[schedule_evidence, *reservation_evidence],
                        recommended_next_action=(
                            "Host should review the turnover and prepare a cleaner follow-up "
                            "for approval."
                        ),
                        requires_attention=True,
                    )
                )
            elif cleaning.confirmation_status == ConfirmationStatus.DECLINED:
                findings.append(
                    SpecialistFinding(
                        finding_id=f"turnover:cleaner_declined:{cleaning.id}",
                        specialist=self.specialist,
                        property_id=cleaning.property_id,
                        category=FindingCategory.CLEANER_DECLINED,
                        severity=FindingSeverity.HIGH,
                        summary="Assigned cleaner declined the turnover.",
                        evidence=[
                            FindingEvidence(
                                source=EvidenceSource.CLEANING_SCHEDULE,
                                record_ids=[cleaning.id],
                                fact=(
                                    f"Cleaning {cleaning.id} has confirmation status declined."
                                ),
                            )
                        ],
                        recommended_next_action="Host should review alternate cleaner coverage.",
                        requires_attention=True,
                    )
                )

            timing_risk = (
                next_reservation is not None
                and cleaning.target_complete_time >= next_reservation.check_in_time
            )
            if timing_risk:
                findings.append(
                    SpecialistFinding(
                        finding_id=f"turnover:timing_risk:{cleaning.id}",
                        specialist=self.specialist,
                        property_id=cleaning.property_id,
                        category=FindingCategory.TURNOVER_TIMING_RISK,
                        severity=FindingSeverity.CRITICAL,
                        summary="Cleaning target is not before the next check-in time.",
                        evidence=[
                            FindingEvidence(
                                source=EvidenceSource.CLEANING_SCHEDULE,
                                record_ids=[cleaning.id],
                                fact=(
                                    f"Cleaning targets {cleaning.target_complete_time.strftime('%H:%M')} "
                                    "completion."
                                ),
                            ),
                            FindingEvidence(
                                source=EvidenceSource.RESERVATIONS,
                                record_ids=[next_reservation.id],
                                fact=(
                                    f"{next_reservation.id} checks in at "
                                    f"{next_reservation.check_in_time.strftime('%H:%M')}."
                                ),
                            ),
                        ],
                        recommended_next_action="Host should review the turnover timing immediately.",
                        requires_attention=True,
                    )
                )
            elif cleaning.confirmation_status == ConfirmationStatus.CONFIRMED:
                state = (
                    "completed" if cleaning.status == CleaningStatus.COMPLETED else "confirmed"
                )
                findings.append(
                    SpecialistFinding(
                        finding_id=f"turnover:on_track:{cleaning.id}",
                        specialist=self.specialist,
                        property_id=cleaning.property_id,
                        category=FindingCategory.TURNOVER_ON_TRACK,
                        severity=FindingSeverity.LOW,
                        summary=(
                            f"Turnover cleaning is {state}."
                            if reservations_failed
                            else (
                                f"Turnover cleaning is {state} with no timing conflict "
                                "in supplied data."
                            )
                        ),
                        evidence=[
                            FindingEvidence(
                                source=EvidenceSource.CLEANING_SCHEDULE,
                                record_ids=[cleaning.id],
                                fact=(
                                    f"Confirmation is {cleaning.confirmation_status.value}; "
                                    f"status is {cleaning.status.value}; target is "
                                    f"{cleaning.target_complete_time.strftime('%H:%M')}."
                                ),
                            )
                        ],
                        recommended_next_action=None,
                        requires_attention=False,
                    )
                )

        if not reservations_failed:
            findings.extend(
                self._missing_schedule_findings(
                    reservations,
                    context.cleaning_schedule,
                    start,
                    end,
                )
            )

        analyzed_ids = [cleaning.id for cleaning in cleanings]
        analyzed_ids.extend(reservation.id for reservation in reservations)
        return self.build_output(context, findings, analyzed_ids)

    def _missing_schedule_findings(
        self,
        reservations: list[Reservation],
        cleanings: list[CleaningSchedule],
        start: date | None,
        end: date | None,
    ) -> list[SpecialistFinding]:
        findings: list[SpecialistFinding] = []
        arrivals = [
            reservation
            for reservation in reservations
            if reservation.status == ReservationStatus.CONFIRMED
            and date_in_scope(reservation.check_in_date, start, end)
        ]
        for arrival in arrivals:
            covered = any(
                cleaning.property_id == arrival.property_id
                and (
                    cleaning.next_reservation_id == arrival.id
                    or (
                        cleaning.scheduled_date <= arrival.check_in_date
                        and arrival.check_in_date - cleaning.scheduled_date
                        <= timedelta(days=7)
                    )
                )
                for cleaning in cleanings
            )
            if covered:
                continue
            findings.append(
                SpecialistFinding(
                    finding_id=f"turnover:missing_schedule:{arrival.id}",
                    specialist=self.specialist,
                    property_id=arrival.property_id,
                    category=FindingCategory.CLEANING_SCHEDULE_MISSING,
                    severity=FindingSeverity.HIGH,
                    summary="No cleaning schedule was supplied for an upcoming arrival.",
                    evidence=[
                        FindingEvidence(
                            source=EvidenceSource.RESERVATIONS,
                            record_ids=[arrival.id],
                            fact=(
                                f"Confirmed reservation {arrival.id} checks in on "
                                f"{arrival.check_in_date.isoformat()}."
                            ),
                        )
                    ],
                    recommended_next_action="Host should review turnover coverage for this arrival.",
                    requires_attention=True,
                )
            )
        return findings
