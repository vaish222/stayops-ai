"""Evidence-preserving prioritization across structured specialist findings."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda

from src.agents.base import SEVERITY_RANK
from src.models import (
    ActionType,
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    OperationsSynthesisInput,
    OperationsSynthesisOutput,
    OverallStatus,
    PrioritizedFinding,
    ProposedAction,
    SpecialistFinding,
    WriteToolName,
)


class OperationsSynthesizer:
    """Combine only supplied specialist findings; never read data or take action."""

    def __init__(self) -> None:
        self.runnable: Runnable[
            OperationsSynthesisInput | dict[str, Any],
            OperationsSynthesisOutput,
        ] = RunnableLambda(
            self._run_validated,
            name="operations_synthesizer",
        ).with_types(
            input_type=OperationsSynthesisInput,
            output_type=OperationsSynthesisOutput,
        )

    def invoke(
        self,
        payload: OperationsSynthesisInput | dict[str, Any],
    ) -> OperationsSynthesisOutput:
        result = self.runnable.invoke(payload)
        return OperationsSynthesisOutput.model_validate(result)

    def _run_validated(
        self,
        payload: OperationsSynthesisInput | dict[str, Any],
    ) -> OperationsSynthesisOutput:
        context = (
            payload
            if isinstance(payload, OperationsSynthesisInput)
            else OperationsSynthesisInput.model_validate(payload)
        )
        return self.synthesize(context)

    def synthesize(
        self,
        context: OperationsSynthesisInput,
    ) -> OperationsSynthesisOutput:
        candidates = self._combine_cross_agent_findings(context.specialist_findings)
        candidates.sort(
            key=lambda finding: (
                -SEVERITY_RANK[finding.severity],
                not finding.requires_attention,
                finding.property_id,
                finding.source_finding_ids,
            )
        )
        prioritized = [
            finding.model_copy(update={"priority_rank": rank})
            for rank, finding in enumerate(candidates, start=1)
        ]
        proposed_actions: list[ProposedAction] = []
        for finding in prioritized:
            if (
                not finding.action_proposed
                or finding.proposed_action_type is None
                or finding.recommended_next_action is None
            ):
                continue
            tool_name, target_record_id, parameters = self._tool_fields_for(finding)
            proposed_actions.append(
                ProposedAction(
                    action_id=f"action:{finding.source_finding_ids[0]}",
                    property_id=finding.property_id,
                    action_type=finding.proposed_action_type,
                    description=finding.recommended_next_action,
                    source_finding_ids=finding.source_finding_ids,
                    tool_name=tool_name,
                    target_record_id=target_record_id,
                    parameters=parameters,
                )
            )
        affected_properties = sorted(
            {
                finding.property_id
                for finding in prioritized
                if finding.requires_attention
            }
        )
        overall_status = self._overall_status(prioritized)
        return OperationsSynthesisOutput(
            overall_status=overall_status,
            prioritized_findings=prioritized,
            affected_properties=affected_properties,
            proposed_actions=proposed_actions,
            action_proposed=bool(proposed_actions),
            briefing=self._briefing(
                overall_status,
                prioritized,
                affected_properties,
            ),
        )

    def _combine_cross_agent_findings(
        self,
        findings: list[SpecialistFinding],
    ) -> list[PrioritizedFinding]:
        same_day_findings = [
            finding
            for finding in findings
            if finding.category == FindingCategory.SAME_DAY_TURNOVER
        ]
        missing_confirmation_findings = [
            finding
            for finding in findings
            if finding.category == FindingCategory.CLEANER_CONFIRMATION_MISSING
        ]
        consumed: set[str] = set()
        combined: list[PrioritizedFinding] = []

        for same_day in same_day_findings:
            reservation_ids = self._evidence_ids(
                same_day,
                EvidenceSource.RESERVATIONS,
            )
            match = next(
                (
                    missing
                    for missing in missing_confirmation_findings
                    if missing.finding_id not in consumed
                    and missing.property_id == same_day.property_id
                    and reservation_ids
                    & self._evidence_ids(missing, EvidenceSource.RESERVATIONS)
                ),
                None,
            )
            if match is None:
                continue
            consumed.update({same_day.finding_id, match.finding_id})
            combined.append(
                self._build_prioritized_finding(
                    [same_day, match],
                    summary="Same-day turnover has a missing cleaner confirmation.",
                )
            )

        combined.extend(
            self._build_prioritized_finding([finding])
            for finding in findings
            if finding.finding_id not in consumed
        )
        return combined

    def _build_prioritized_finding(
        self,
        contributors: list[SpecialistFinding],
        *,
        summary: str | None = None,
    ) -> PrioritizedFinding:
        ordered = sorted(
            contributors,
            key=lambda finding: -SEVERITY_RANK[finding.severity],
        )
        recommended_action = next(
            (
                finding.recommended_next_action
                for finding in ordered
                if finding.recommended_next_action
            ),
            None,
        )
        requires_attention = any(
            finding.requires_attention for finding in contributors
        )
        if not requires_attention:
            recommended_action = None
        proposed_action_type: ActionType | None = None
        if recommended_action is not None:
            proposed_action_type, recommended_action = self._action_spec(
                contributors,
                recommended_action,
            )
        evidence: list[FindingEvidence] = []
        seen_evidence: set[tuple[str, tuple[str, ...], str]] = set()
        for finding in contributors:
            for item in finding.evidence:
                key = (item.source.value, tuple(item.record_ids), item.fact)
                if key not in seen_evidence:
                    seen_evidence.add(key)
                    evidence.append(item)

        return PrioritizedFinding(
            priority_rank=1,
            property_id=contributors[0].property_id,
            severity=ordered[0].severity,
            summary=summary or contributors[0].summary,
            specialist_sources=list(
                dict.fromkeys(finding.specialist for finding in contributors)
            ),
            categories=list(dict.fromkeys(finding.category for finding in contributors)),
            source_finding_ids=[finding.finding_id for finding in contributors],
            evidence=evidence,
            recommended_next_action=recommended_action,
            proposed_action_type=proposed_action_type,
            requires_attention=requires_attention,
            action_proposed=recommended_action is not None,
            confidence=min(finding.confidence for finding in contributors),
        )

    @staticmethod
    def _action_spec(
        contributors: list[SpecialistFinding],
        fallback_description: str,
    ) -> tuple[ActionType, str]:
        guest_message_categories = {
            FindingCategory.UNANSWERED_MESSAGE,
            FindingCategory.EARLY_CHECK_IN_REQUEST,
            FindingCategory.GUEST_COMPLAINT,
            FindingCategory.GUEST_MAINTENANCE_REPORT,
        }
        categories = {finding.category for finding in contributors}
        evidence_sources = {
            evidence.source
            for finding in contributors
            for evidence in finding.evidence
        }
        if (
            categories & guest_message_categories
            and EvidenceSource.GUEST_MESSAGES in evidence_sources
        ):
            return (
                ActionType.SEND_MESSAGE,
                "Thanks for your message. I am reviewing it and will follow up shortly.",
            )
        if (
            FindingCategory.CLEANER_CONFIRMATION_MISSING in categories
            and EvidenceSource.CLEANING_SCHEDULE in evidence_sources
        ):
            return (
                ActionType.SEND_MESSAGE,
                "Please confirm whether the scheduled turnover will be completed "
                "by the target time.",
            )
        maintenance_categories = {
            FindingCategory.OPEN_MAINTENANCE,
            FindingCategory.GUEST_IMPACTING_MAINTENANCE,
            FindingCategory.UPCOMING_STAY_MAINTENANCE_RISK,
        }
        if (
            categories & maintenance_categories
            and EvidenceSource.MAINTENANCE_TICKETS in evidence_sources
        ):
            return (
                ActionType.UPDATE_RECORD,
                "Update the maintenance ticket status to in_progress.",
            )
        return ActionType.REVIEW, fallback_description

    @staticmethod
    def _tool_fields_for(
        finding: PrioritizedFinding,
    ) -> tuple[WriteToolName | None, str | None, dict[str, str]]:
        if finding.proposed_action_type == ActionType.SEND_MESSAGE:
            if FindingCategory.CLEANER_CONFIRMATION_MISSING in finding.categories:
                tool_name = WriteToolName.SEND_CLEANER_MESSAGE
                source = EvidenceSource.CLEANING_SCHEDULE
            else:
                tool_name = WriteToolName.SEND_GUEST_MESSAGE
                source = EvidenceSource.GUEST_MESSAGES
            target_record_id = OperationsSynthesizer._first_evidence_id(
                finding,
                source,
            )
            return (
                tool_name,
                target_record_id,
                {"message": finding.recommended_next_action or ""},
            )
        if finding.proposed_action_type == ActionType.UPDATE_RECORD:
            return (
                WriteToolName.UPDATE_MAINTENANCE_STATUS,
                OperationsSynthesizer._first_evidence_id(
                    finding,
                    EvidenceSource.MAINTENANCE_TICKETS,
                ),
                {"status": "in_progress"},
            )
        return None, None, {}

    @staticmethod
    def _first_evidence_id(
        finding: PrioritizedFinding,
        source: EvidenceSource,
    ) -> str:
        return next(
            record_id
            for evidence in finding.evidence
            if evidence.source == source
            for record_id in evidence.record_ids
        )

    @staticmethod
    def _evidence_ids(
        finding: SpecialistFinding,
        source: EvidenceSource,
    ) -> set[str]:
        return {
            record_id
            for evidence in finding.evidence
            if evidence.source == source
            for record_id in evidence.record_ids
        }

    @staticmethod
    def _overall_status(findings: list[PrioritizedFinding]) -> OverallStatus:
        if not findings:
            return OverallStatus.NO_FINDINGS
        attention_severities = {
            finding.severity for finding in findings if finding.requires_attention
        }
        if attention_severities & {FindingSeverity.CRITICAL, FindingSeverity.HIGH}:
            return OverallStatus.NEEDS_ATTENTION
        if FindingSeverity.MEDIUM in attention_severities:
            return OverallStatus.WATCH
        return OverallStatus.READY

    @staticmethod
    def _briefing(
        status: OverallStatus,
        findings: list[PrioritizedFinding],
        affected_properties: list[str],
    ) -> str:
        if status == OverallStatus.NO_FINDINGS:
            return "No structured specialist findings were supplied."
        attention_count = sum(finding.requires_attention for finding in findings)
        if attention_count == 0:
            return "Based on supplied specialist findings, no item requires attention."
        property_label = "property" if len(affected_properties) == 1 else "properties"
        item_label = "item" if attention_count == 1 else "items"
        return (
            f"Overall status: {status.value.replace('_', ' ')}. "
            f"{attention_count} prioritized {item_label} across "
            f"{len(affected_properties)} affected {property_label}."
        )
