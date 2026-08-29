"""Phase 6 deterministic risk/action gate and graph-boundary tests."""

from __future__ import annotations

from datetime import date

import pytest

from src.graph import build_phase_6_graph, create_initial_state
from src.models import (
    ActionType,
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    ProposedAction,
    ReviewReasonCode,
    RiskGateConfig,
    RiskGateInput,
    SpecialistFinding,
    SpecialistName,
    WriteToolName,
)
from src.safety import RiskActionGate


REFERENCE_DATE = date(2026, 8, 28)


def make_finding(
    *,
    finding_id: str = "booking:arrival:test",
    specialist: SpecialistName = SpecialistName.BOOKING,
    category: FindingCategory = FindingCategory.ARRIVAL,
    severity: FindingSeverity = FindingSeverity.LOW,
    property_id: str = "prop_city_loft",
    record_id: str = "res_city_001",
    confidence: float = 1.0,
) -> SpecialistFinding:
    return SpecialistFinding(
        finding_id=finding_id,
        specialist=specialist,
        property_id=property_id,
        category=category,
        severity=severity,
        summary=f"Supported {category.value} finding.",
        evidence=[
            FindingEvidence(
                source=EvidenceSource.RESERVATIONS,
                record_ids=[record_id],
                fact=f"Evidence from {record_id}.",
            )
        ],
        recommended_next_action=None,
        requires_attention=False,
        confidence=confidence,
    )


def make_action(action_type: ActionType) -> ProposedAction:
    description = f"Perform {action_type.value}."
    executable_fields = {}
    if action_type == ActionType.SEND_MESSAGE:
        executable_fields = {
            "tool_name": WriteToolName.SEND_GUEST_MESSAGE,
            "target_record_id": "msg_test_001",
            "parameters": {"message": description},
        }
    elif action_type == ActionType.UPDATE_RECORD:
        executable_fields = {
            "tool_name": WriteToolName.UPDATE_MAINTENANCE_STATUS,
            "target_record_id": "maint_test_001",
            "parameters": {"status": "in_progress"},
        }
    return ProposedAction(
        action_id=f"action:{action_type.value}:test",
        property_id="prop_city_loft",
        action_type=action_type,
        description=description,
        source_finding_ids=["booking:arrival:test"],
        **executable_fields,
    )


def evaluate(
    *,
    write_requested: bool = False,
    findings: list[SpecialistFinding] | None = None,
    actions: list[ProposedAction] | None = None,
    gate: RiskActionGate | None = None,
):
    return (gate or RiskActionGate()).evaluate(
        RiskGateInput(
            write_requested=write_requested,
            specialist_findings=findings or [],
            prioritized_findings=[],
            proposed_actions=actions or [],
        )
    )


def reason_codes(output) -> list[ReviewReasonCode]:
    return [reason.code for reason in output.reasons]


@pytest.mark.parametrize("safe_action", [ActionType.REVIEW, ActionType.DRAFT_MESSAGE])
def test_safe_read_only_or_draft_actions_do_not_require_review(
    safe_action: ActionType,
) -> None:
    output = evaluate(
        findings=[make_finding()],
        actions=[make_action(safe_action)],
    )

    assert output.requires_human_review is False
    assert output.reasons == []


def test_router_write_intent_requires_review_with_explicit_reason() -> None:
    output = evaluate(write_requested=True)

    assert output.requires_human_review is True
    assert reason_codes(output) == [ReviewReasonCode.WRITE_REQUESTED]
    assert output.reasons[0].source_ids == ["router:write_requested"]


@pytest.mark.parametrize(
    ("action_type", "expected_reason"),
    [
        (ActionType.SEND_MESSAGE, ReviewReasonCode.MESSAGE_SEND),
        (
            ActionType.MODIFY_RESERVATION,
            ReviewReasonCode.RESERVATION_MODIFICATION,
        ),
        (ActionType.UPDATE_RECORD, ReviewReasonCode.RECORD_UPDATE),
    ],
)
def test_each_write_action_requires_review(
    action_type: ActionType,
    expected_reason: ReviewReasonCode,
) -> None:
    output = evaluate(actions=[make_action(action_type)])

    assert output.requires_human_review is True
    assert reason_codes(output) == [expected_reason]
    assert output.reasons[0].property_ids == ["prop_city_loft"]
    assert output.reasons[0].source_ids[0] == f"action:{action_type.value}:test"


@pytest.mark.parametrize(
    "severity",
    [FindingSeverity.HIGH, FindingSeverity.CRITICAL],
)
def test_high_or_critical_maintenance_requires_review(
    severity: FindingSeverity,
) -> None:
    finding = make_finding(
        finding_id=f"maintenance:{severity.value}:test",
        specialist=SpecialistName.MAINTENANCE,
        category=FindingCategory.OPEN_MAINTENANCE,
        severity=severity,
    )

    output = evaluate(findings=[finding])

    assert reason_codes(output) == [ReviewReasonCode.HIGH_MAINTENANCE_SEVERITY]
    assert output.reasons[0].source_ids == [finding.finding_id]


def test_maintenance_rule_does_not_gate_medium_or_nonmaintenance_findings() -> None:
    findings = [
        make_finding(
            finding_id="maintenance:medium:test",
            specialist=SpecialistName.MAINTENANCE,
            category=FindingCategory.OPEN_MAINTENANCE,
            severity=FindingSeverity.MEDIUM,
        ),
        make_finding(
            finding_id="booking:high:test",
            specialist=SpecialistName.BOOKING,
            category=FindingCategory.RESERVATION_CONFLICT,
            severity=FindingSeverity.HIGH,
        ),
    ]

    assert evaluate(findings=findings).requires_human_review is False


def test_confidence_below_threshold_requires_review() -> None:
    finding = make_finding(confidence=0.74)

    output = evaluate(findings=[finding])

    assert reason_codes(output) == [ReviewReasonCode.LOW_CONFIDENCE]
    assert "0.74" in output.reasons[0].message
    assert "0.75" in output.reasons[0].message


def test_confidence_at_threshold_does_not_require_review() -> None:
    gate = RiskActionGate(RiskGateConfig(low_confidence_threshold=0.6))

    assert evaluate(findings=[make_finding(confidence=0.6)], gate=gate).reasons == []
    assert reason_codes(
        evaluate(findings=[make_finding(confidence=0.59)], gate=gate)
    ) == [ReviewReasonCode.LOW_CONFIDENCE]


def test_conflicting_findings_with_shared_evidence_require_review() -> None:
    findings = [
        make_finding(
            finding_id="turnover:on-track:test",
            specialist=SpecialistName.TURNOVER,
            category=FindingCategory.TURNOVER_ON_TRACK,
            record_id="res_shared_001",
        ),
        make_finding(
            finding_id="booking:timing-risk:test",
            specialist=SpecialistName.BOOKING,
            category=FindingCategory.TURNOVER_TIMING_RISK,
            severity=FindingSeverity.HIGH,
            record_id="res_shared_001",
        ),
    ]

    output = evaluate(findings=findings)

    assert reason_codes(output) == [ReviewReasonCode.CONFLICTING_FINDINGS]
    assert set(output.reasons[0].source_ids) == {
        "turnover:on-track:test",
        "booking:timing-risk:test",
    }


def test_findings_do_not_conflict_without_same_property_and_shared_evidence() -> None:
    base = make_finding(
        finding_id="turnover:on-track:test",
        specialist=SpecialistName.TURNOVER,
        category=FindingCategory.TURNOVER_ON_TRACK,
        record_id="res_city_001",
    )
    different_evidence = make_finding(
        finding_id="booking:timing-risk:different-evidence",
        category=FindingCategory.TURNOVER_TIMING_RISK,
        severity=FindingSeverity.HIGH,
        record_id="res_city_002",
    )
    different_property = make_finding(
        finding_id="booking:timing-risk:different-property",
        category=FindingCategory.TURNOVER_TIMING_RISK,
        severity=FindingSeverity.HIGH,
        property_id="prop_lake_house",
        record_id="res_city_001",
    )

    output = evaluate(findings=[base, different_evidence, different_property])

    assert ReviewReasonCode.CONFLICTING_FINDINGS not in reason_codes(output)


def test_gate_aggregates_all_applicable_reasons_without_executing_actions() -> None:
    maintenance = make_finding(
        finding_id="maintenance:high:low-confidence",
        specialist=SpecialistName.MAINTENANCE,
        category=FindingCategory.OPEN_MAINTENANCE,
        severity=FindingSeverity.HIGH,
        confidence=0.5,
    )
    action = make_action(ActionType.UPDATE_RECORD)

    output = evaluate(
        write_requested=True,
        findings=[maintenance],
        actions=[action],
    )

    assert reason_codes(output) == [
        ReviewReasonCode.WRITE_REQUESTED,
        ReviewReasonCode.RECORD_UPDATE,
        ReviewReasonCode.HIGH_MAINTENANCE_SEVERITY,
        ReviewReasonCode.LOW_CONFIDENCE,
    ]
    assert action.executed is False


def test_phase_6_graph_runs_gate_after_synthesis_for_high_maintenance() -> None:
    graph = build_phase_6_graph(reference_date=REFERENCE_DATE)

    result = graph.invoke(
        create_initial_state(
            "What needs my attention today?",
            request_id="phase-6-high-maintenance",
        )
    )

    assert result["risk_gate_evaluated"] is True
    assert result["requires_human_review"] is True
    assert ReviewReasonCode.HIGH_MAINTENANCE_SEVERITY in {
        reason["code"] for reason in result["review_reasons"]
    }
    assert result["operational_findings"]
    assert result["executed_actions"] == []


def test_phase_6_graph_preserves_safe_read_only_path() -> None:
    graph = build_phase_6_graph(reference_date=REFERENCE_DATE)

    result = graph.invoke(
        create_initial_state(
            "Which guests are arriving at City Loft today?",
            request_id="phase-6-safe-read",
        )
    )

    assert result["risk_gate_evaluated"] is True
    assert result["requires_human_review"] is False
    assert result["review_reasons"] == []
    assert result["executed_actions"] == []


def test_phase_6_graph_gates_router_write_intent_without_executing_it() -> None:
    graph = build_phase_6_graph(reference_date=REFERENCE_DATE)

    result = graph.invoke(
        create_initial_state(
            "Send the guest at City Loft a message.",
            request_id="phase-6-write-intent",
        )
    )

    assert result["write_requested"] is True
    assert result["requires_human_review"] is True
    assert result["review_reasons"][0]["code"] == ReviewReasonCode.WRITE_REQUESTED
    assert result["executed_actions"] == []


def test_phase_6_graph_contains_gate_but_no_hitl_or_execution_nodes() -> None:
    graph = build_phase_6_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert "risk_action_gate" in node_names
    assert not {
        "human_review",
        "approve_action",
        "edit_action",
        "reject_action",
        "execute_action",
    } & node_names


class FailingGate:
    def evaluate(self, payload):
        raise RuntimeError("synthetic gate failure")


def test_gate_failure_defaults_to_review_and_records_an_error() -> None:
    graph = build_phase_6_graph(
        reference_date=REFERENCE_DATE,
        gate_runner=FailingGate(),
    )

    result = graph.invoke(
        create_initial_state(
            "Which guests are arriving at City Loft today?",
            request_id="phase-6-gate-failure",
        )
    )

    assert result["risk_gate_evaluated"] is False
    assert result["requires_human_review"] is True
    assert result["review_reasons"][0]["code"] == (
        ReviewReasonCode.GATE_EVALUATION_ERROR
    )
    assert result["errors"][-1]["stage"] == "risk_gate_execution"
    assert result["executed_actions"] == []
