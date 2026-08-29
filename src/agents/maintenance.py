"""Maintenance specialist for severity, guest impact, and stay impact."""

from __future__ import annotations

from src.agents.base import (
    BaseSpecialistAgent,
    property_in_scope,
    severity_at_least,
)
from src.models import (
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    MaintenanceAgentInput,
    MaintenanceSeverity,
    MaintenanceStatus,
    ReservationStatus,
    SpecialistFinding,
    SpecialistName,
    SpecialistOutput,
)
from src.tools import ReadToolName


MAINTENANCE_TO_FINDING_SEVERITY = {
    MaintenanceSeverity.LOW: FindingSeverity.LOW,
    MaintenanceSeverity.MEDIUM: FindingSeverity.MEDIUM,
    MaintenanceSeverity.HIGH: FindingSeverity.HIGH,
    MaintenanceSeverity.CRITICAL: FindingSeverity.CRITICAL,
}


class MaintenanceAgent(BaseSpecialistAgent[MaintenanceAgentInput]):
    input_model = MaintenanceAgentInput
    specialist = SpecialistName.MAINTENANCE

    def analyze(self, context: MaintenanceAgentInput) -> SpecialistOutput:
        failed_tools = self.failed_source_tools(context)
        if ReadToolName.GET_MAINTENANCE_TICKETS.value in failed_tools:
            return self.build_output(context, [], [])

        reservations_available = ReadToolName.GET_RESERVATIONS.value not in failed_tools
        start, end = context.date_bounds()
        tickets = [
            ticket
            for ticket in context.maintenance_tickets
            if property_in_scope(ticket.property_id, context.property_scope)
            and (end is None or ticket.created_at.date() <= end)
            and not (
                start is not None
                and ticket.status == MaintenanceStatus.RESOLVED
                and ticket.updated_at.date() < start
            )
        ]
        reservations = [
            reservation
            for reservation in context.reservations
            if property_in_scope(reservation.property_id, context.property_scope)
        ]
        findings: list[SpecialistFinding] = []

        for ticket in tickets:
            if ticket.status == MaintenanceStatus.RESOLVED:
                continue

            upcoming = []
            if reservations_available:
                upcoming = [
                    reservation
                    for reservation in reservations
                    if reservation.property_id == ticket.property_id
                    and reservation.status == ReservationStatus.CONFIRMED
                    and reservation.check_in_date >= ticket.created_at.date()
                ]

            category = FindingCategory.OPEN_MAINTENANCE
            severity = MAINTENANCE_TO_FINDING_SEVERITY[ticket.severity]
            summary = f"Open maintenance ticket: {ticket.summary}."
            if ticket.blocks_checkin and upcoming:
                category = FindingCategory.UPCOMING_STAY_MAINTENANCE_RISK
                severity = severity_at_least(severity, FindingSeverity.HIGH)
                summary = "Open maintenance ticket is marked as blocking an upcoming check-in."
            elif ticket.guest_impact:
                category = FindingCategory.GUEST_IMPACTING_MAINTENANCE
                severity = severity_at_least(severity, FindingSeverity.HIGH)
                summary = "Open maintenance ticket is marked as impacting a guest."

            evidence = [
                FindingEvidence(
                    source=EvidenceSource.MAINTENANCE_TICKETS,
                    record_ids=[ticket.id],
                    fact=(
                        f"Ticket severity is {ticket.severity.value}, status is "
                        f"{ticket.status.value}, guest_impact={ticket.guest_impact}, and "
                        f"blocks_checkin={ticket.blocks_checkin}."
                    ),
                )
            ]
            if ticket.blocks_checkin and upcoming:
                evidence.append(
                    FindingEvidence(
                        source=EvidenceSource.RESERVATIONS,
                        record_ids=[reservation.id for reservation in upcoming],
                        fact=(
                            "Confirmed upcoming check-in dates: "
                            + ", ".join(
                                f"{reservation.id}={reservation.check_in_date.isoformat()}"
                                for reservation in upcoming
                            )
                            + "."
                        ),
                    )
                )

            findings.append(
                SpecialistFinding(
                    finding_id=f"maintenance:{category.value}:{ticket.id}",
                    specialist=self.specialist,
                    property_id=ticket.property_id,
                    category=category,
                    severity=severity,
                    summary=summary,
                    evidence=evidence,
                    recommended_next_action=(
                        "Host should review the ticket and coordinate the next maintenance step."
                    ),
                    requires_attention=True,
                )
            )

        analyzed_ids = [ticket.id for ticket in tickets]
        if reservations_available:
            analyzed_ids.extend(reservation.id for reservation in reservations)
        return self.build_output(context, findings, analyzed_ids)
