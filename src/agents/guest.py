"""Guest specialist for unanswered requests, complaints, and issue reports."""

from __future__ import annotations

from src.agents.base import (
    BaseSpecialistAgent,
    date_in_scope,
    property_in_scope,
    severity_at_least,
)
from src.models import (
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    GuestAgentInput,
    MessageCategory,
    MessageDirection,
    MessageUrgency,
    SpecialistFinding,
    SpecialistName,
    SpecialistOutput,
)
from src.tools import ReadToolName


URGENCY_TO_SEVERITY = {
    MessageUrgency.LOW: FindingSeverity.LOW,
    MessageUrgency.MEDIUM: FindingSeverity.MEDIUM,
    MessageUrgency.HIGH: FindingSeverity.HIGH,
    MessageUrgency.CRITICAL: FindingSeverity.CRITICAL,
}


class GuestAgent(BaseSpecialistAgent[GuestAgentInput]):
    input_model = GuestAgentInput
    specialist = SpecialistName.GUEST

    def analyze(self, context: GuestAgentInput) -> SpecialistOutput:
        if ReadToolName.GET_GUEST_MESSAGES.value in self.failed_source_tools(context):
            return self.build_output(context, [], [])

        start, end = context.date_bounds()
        messages = [
            message
            for message in context.guest_messages
            if property_in_scope(message.property_id, context.property_scope)
            and date_in_scope(message.received_at.date(), start, end)
        ]
        findings: list[SpecialistFinding] = []
        for message in messages:
            if (
                message.direction != MessageDirection.INBOUND
                or not message.requires_response
                or message.responded_at is not None
            ):
                continue

            category = FindingCategory.UNANSWERED_MESSAGE
            severity = URGENCY_TO_SEVERITY[message.urgency]
            if message.category == MessageCategory.EARLY_CHECK_IN:
                category = FindingCategory.EARLY_CHECK_IN_REQUEST
                severity = severity_at_least(severity, FindingSeverity.MEDIUM)
            elif message.category == MessageCategory.COMPLAINT:
                category = FindingCategory.GUEST_COMPLAINT
                severity = severity_at_least(severity, FindingSeverity.HIGH)
            elif message.category == MessageCategory.MAINTENANCE:
                category = FindingCategory.GUEST_MAINTENANCE_REPORT
                severity = severity_at_least(severity, FindingSeverity.HIGH)

            findings.append(
                SpecialistFinding(
                    finding_id=f"guest:{category.value}:{message.id}",
                    specialist=self.specialist,
                    property_id=message.property_id,
                    category=category,
                    severity=severity,
                    summary=self._summary_for(category),
                    evidence=[
                        FindingEvidence(
                            source=EvidenceSource.GUEST_MESSAGES,
                            record_ids=[message.id],
                            fact=(
                                f"Inbound {message.urgency.value} message received at "
                                f"{message.received_at.isoformat()} has no recorded response: "
                                f"{message.body}"
                            ),
                        )
                    ],
                    recommended_next_action=(
                        "Host should review the message and, if appropriate, draft a response "
                        "for approval."
                    ),
                    requires_attention=True,
                )
            )

        return self.build_output(
            context,
            findings,
            [message.id for message in messages],
        )

    @staticmethod
    def _summary_for(category: FindingCategory) -> str:
        summaries = {
            FindingCategory.EARLY_CHECK_IN_REQUEST: "Early check-in request is unanswered.",
            FindingCategory.GUEST_COMPLAINT: "Guest complaint is unanswered.",
            FindingCategory.GUEST_MAINTENANCE_REPORT: (
                "Guest maintenance report is unanswered."
            ),
            FindingCategory.UNANSWERED_MESSAGE: "Guest message requiring a response is unanswered.",
        }
        return summaries[category]
