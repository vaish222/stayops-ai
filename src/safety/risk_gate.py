"""Deterministic Phase 6 review rules. No LLM or write tool is used here."""

from __future__ import annotations

from src.models import (
    ActionType,
    FindingCategory,
    FindingSeverity,
    HumanReviewReason,
    OperationalWarning,
    ReviewReasonCode,
    RiskGateConfig,
    RiskGateInput,
    RiskGateOutput,
    SpecialistFinding,
    SpecialistName,
)


ACTION_REVIEW_RULES = {
    ActionType.SEND_MESSAGE: (
        ReviewReasonCode.MESSAGE_SEND,
        "Sending a message requires explicit human approval.",
    ),
    ActionType.MODIFY_RESERVATION: (
        ReviewReasonCode.RESERVATION_MODIFICATION,
        "Modifying a reservation requires explicit human approval.",
    ),
    ActionType.UPDATE_RECORD: (
        ReviewReasonCode.RECORD_UPDATE,
        "Updating an operational record requires explicit human approval.",
    ),
}

CONFLICTING_CATEGORY_PAIRS = {
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANER_CONFIRMATION_MISSING,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANER_DECLINED,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.TURNOVER_TIMING_RISK,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANING_SCHEDULE_MISSING,
        }
    ),
}


class RiskActionGate:
    """Evaluate hard review rules in stable, inspectable Python code."""

    def __init__(self, config: RiskGateConfig | None = None) -> None:
        self.config = config or RiskGateConfig()

    def evaluate(self, payload: RiskGateInput | dict) -> RiskGateOutput:
        context = (
            payload
            if isinstance(payload, RiskGateInput)
            else RiskGateInput.model_validate(payload)
        )
        reasons: list[HumanReviewReason] = []
        advisories: list[OperationalWarning] = []

        if context.unavailable_sources:
            advisories.append(
                OperationalWarning(
                    code=ReviewReasonCode.SOURCE_DATA_UNAVAILABLE,
                    message=(
                        "Required source data remained unavailable after retry. "
                        "The findings are partial and must not be treated as an all-clear."
                    ),
                    source_ids=context.unavailable_sources,
                )
            )

        if not context.synthesis_complete:
            advisories.append(
                OperationalWarning(
                    code=ReviewReasonCode.SYNTHESIS_UNAVAILABLE,
                    message=(
                        "Operations synthesis could not be completed; the result "
                        "is incomplete."
                    ),
                    source_ids=["operations_synthesizer"],
                )
            )

        if context.write_requested:
            reasons.append(
                HumanReviewReason(
                    code=ReviewReasonCode.WRITE_REQUESTED,
                    message="The host request was classified as potentially write-producing.",
                    source_ids=["router:write_requested"],
                    property_ids=sorted(
                        {action.property_id for action in context.proposed_actions}
                    ),
                )
            )

        # Synthesized actions are recommendations for read-only questions.  They
        # become approval candidates only when the router detected write intent.
        if context.write_requested:
            for action in context.proposed_actions:
                rule = ACTION_REVIEW_RULES.get(action.action_type)
                if rule is None:
                    continue
                code, message = rule
                reasons.append(
                    HumanReviewReason(
                        code=code,
                        message=message,
                        source_ids=[action.action_id, *action.source_finding_ids],
                        property_ids=[action.property_id],
                    )
                )

        for finding in context.specialist_findings:
            if (
                finding.specialist == SpecialistName.MAINTENANCE
                and finding.severity
                in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}
            ):
                advisories.append(
                    OperationalWarning(
                        code=ReviewReasonCode.HIGH_MAINTENANCE_SEVERITY,
                        message=(
                            "High- or critical-severity maintenance needs prompt attention."
                        ),
                        source_ids=[finding.finding_id],
                        property_ids=[finding.property_id],
                    )
                )

        covered_low_confidence_ids: set[str] = set()
        for finding in context.prioritized_findings:
            if finding.confidence < self.config.low_confidence_threshold:
                covered_low_confidence_ids.update(finding.source_finding_ids)
                advisories.append(
                    OperationalWarning(
                        code=ReviewReasonCode.LOW_CONFIDENCE,
                        message=(
                            f"Finding confidence {finding.confidence:.2f} is below the "
                            f"{self.config.low_confidence_threshold:.2f} confidence threshold."
                        ),
                        source_ids=finding.source_finding_ids,
                        property_ids=[finding.property_id],
                    )
                )
        for finding in context.specialist_findings:
            if (
                finding.confidence < self.config.low_confidence_threshold
                and finding.finding_id not in covered_low_confidence_ids
            ):
                advisories.append(
                    OperationalWarning(
                        code=ReviewReasonCode.LOW_CONFIDENCE,
                        message=(
                            f"Finding confidence {finding.confidence:.2f} is below the "
                            f"{self.config.low_confidence_threshold:.2f} confidence threshold."
                        ),
                        source_ids=[finding.finding_id],
                        property_ids=[finding.property_id],
                    )
                )

        advisories.extend(self._conflict_warnings(context.specialist_findings))
        return RiskGateOutput(
            requires_human_review=bool(reasons),
            reasons=reasons,
            advisories=advisories,
        )

    @staticmethod
    def _conflict_warnings(
        findings: list[SpecialistFinding],
    ) -> list[OperationalWarning]:
        warnings: list[OperationalWarning] = []
        ordered = sorted(findings, key=lambda finding: finding.finding_id)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if left.property_id != right.property_id:
                    continue
                if frozenset({left.category, right.category}) not in CONFLICTING_CATEGORY_PAIRS:
                    continue
                if not RiskActionGate._evidence_ids(left) & RiskActionGate._evidence_ids(right):
                    continue
                warnings.append(
                    OperationalWarning(
                        code=ReviewReasonCode.CONFLICTING_FINDINGS,
                        message=(
                            "Specialist findings make conflicting claims about the same "
                            "evidence-backed turnover."
                        ),
                        source_ids=[left.finding_id, right.finding_id],
                        property_ids=[left.property_id],
                    )
                )
        return warnings

    @staticmethod
    def _evidence_ids(finding: SpecialistFinding) -> set[str]:
        return {
            record_id
            for evidence in finding.evidence
            for record_id in evidence.record_ids
        }
