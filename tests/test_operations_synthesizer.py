"""Phase 5 synthesis, prioritization, evidence, and graph-boundary tests."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.agents import OperationsSynthesizer
from src.graph import (
    build_phase_4_graph,
    build_phase_5_graph,
    create_initial_state,
)
from src.models import (
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    OperationsSynthesisInput,
    OperationsSynthesisOutput,
    OverallStatus,
    SpecialistFinding,
    SpecialistName,
    SynthesisInvocation,
)


REFERENCE_DATE = date(2026, 8, 28)


def make_finding(
    *,
    finding_id: str,
    specialist: SpecialistName,
    category: FindingCategory,
    severity: FindingSeverity,
    property_id: str = "prop_lake_house",
    reservation_id: str = "res_test_001",
    requires_attention: bool = True,
    recommended_action: str | None = "Review the supported issue.",
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
                record_ids=[reservation_id],
                fact=f"Supplied reservation evidence from {reservation_id}.",
            )
        ],
        recommended_next_action=recommended_action,
        requires_attention=requires_attention,
    )


def lake_phase_4_findings() -> list[dict]:
    graph = build_phase_4_graph(reference_date=REFERENCE_DATE)
    result = graph.invoke(
        create_initial_state(
            "Is Lake House turnover ready for today's arrival?",
            request_id="phase-5-source",
        )
    )
    return [
        *result["booking_findings"],
        *result["guest_findings"],
        *result["turnover_findings"],
        *result["maintenance_findings"],
    ]


def test_synthesizer_combines_same_day_turnover_with_missing_confirmation() -> None:
    source_findings = lake_phase_4_findings()

    output = OperationsSynthesizer().invoke(
        {"specialist_findings": source_findings}
    )

    top = output.prioritized_findings[0]
    assert output.overall_status == OverallStatus.NEEDS_ATTENTION
    assert top.priority_rank == 1
    assert top.property_id == "prop_lake_house"
    assert top.severity == FindingSeverity.HIGH
    assert top.summary == "Same-day turnover has a missing cleaner confirmation."
    assert set(top.specialist_sources) == {
        SpecialistName.BOOKING,
        SpecialistName.TURNOVER,
    }
    assert set(top.categories) == {
        FindingCategory.SAME_DAY_TURNOVER,
        FindingCategory.CLEANER_CONFIRMATION_MISSING,
    }
    assert set(top.source_finding_ids) == {
        "booking:same_day:prop_lake_house:2026-08-28",
        "turnover:confirmation_missing:clean_lake_001",
    }
    assert output.affected_properties == ["prop_lake_house"]
    assert output.action_proposed is True
    assert output.proposed_actions[0].executed is False
    assert len(output.prioritized_findings) == len(source_findings) - 1


def test_combination_preserves_all_and_only_contributor_evidence() -> None:
    source_findings = OperationsSynthesisInput(
        specialist_findings=lake_phase_4_findings()
    ).specialist_findings
    source_by_id = {finding.finding_id: finding for finding in source_findings}

    output = OperationsSynthesizer().invoke(
        OperationsSynthesisInput(specialist_findings=source_findings)
    )

    for prioritized in output.prioritized_findings:
        expected = {
            (evidence.source, tuple(evidence.record_ids), evidence.fact)
            for finding_id in prioritized.source_finding_ids
            for evidence in source_by_id[finding_id].evidence
        }
        actual = {
            (evidence.source, tuple(evidence.record_ids), evidence.fact)
            for evidence in prioritized.evidence
        }
        assert actual == expected


def test_same_property_findings_without_shared_evidence_are_not_combined() -> None:
    same_day = make_finding(
        finding_id="booking:same-day:test",
        specialist=SpecialistName.BOOKING,
        category=FindingCategory.SAME_DAY_TURNOVER,
        severity=FindingSeverity.MEDIUM,
        reservation_id="res_unrelated_001",
    )
    missing_confirmation = make_finding(
        finding_id="turnover:missing:test",
        specialist=SpecialistName.TURNOVER,
        category=FindingCategory.CLEANER_CONFIRMATION_MISSING,
        severity=FindingSeverity.HIGH,
        reservation_id="res_unrelated_002",
    )

    output = OperationsSynthesizer().invoke(
        {"specialist_findings": [same_day, missing_confirmation]}
    )

    assert len(output.prioritized_findings) == 2
    assert all(
        len(finding.source_finding_ids) == 1
        for finding in output.prioritized_findings
    )


@pytest.mark.parametrize(
    ("findings", "expected_status"),
    [
        ([], OverallStatus.NO_FINDINGS),
        (
            [
                make_finding(
                    finding_id="low:routine",
                    specialist=SpecialistName.BOOKING,
                    category=FindingCategory.ARRIVAL,
                    severity=FindingSeverity.LOW,
                    requires_attention=False,
                    recommended_action=None,
                )
            ],
            OverallStatus.READY,
        ),
        (
            [
                make_finding(
                    finding_id="medium:watch",
                    specialist=SpecialistName.BOOKING,
                    category=FindingCategory.SAME_DAY_TURNOVER,
                    severity=FindingSeverity.MEDIUM,
                )
            ],
            OverallStatus.WATCH,
        ),
        (
            [
                make_finding(
                    finding_id="high:attention",
                    specialist=SpecialistName.MAINTENANCE,
                    category=FindingCategory.OPEN_MAINTENANCE,
                    severity=FindingSeverity.HIGH,
                )
            ],
            OverallStatus.NEEDS_ATTENTION,
        ),
    ],
)
def test_overall_status_is_derived_from_supplied_findings(
    findings: list[SpecialistFinding],
    expected_status: OverallStatus,
) -> None:
    output = OperationsSynthesizer().invoke(
        {"specialist_findings": findings}
    )

    assert output.overall_status == expected_status


def test_priorities_are_contiguous_and_severity_ordered() -> None:
    findings = [
        make_finding(
            finding_id="low:test",
            specialist=SpecialistName.BOOKING,
            category=FindingCategory.ARRIVAL,
            severity=FindingSeverity.LOW,
            requires_attention=False,
            recommended_action=None,
        ),
        make_finding(
            finding_id="critical:test",
            specialist=SpecialistName.MAINTENANCE,
            category=FindingCategory.OPEN_MAINTENANCE,
            severity=FindingSeverity.CRITICAL,
        ),
        make_finding(
            finding_id="medium:test",
            specialist=SpecialistName.GUEST,
            category=FindingCategory.EARLY_CHECK_IN_REQUEST,
            severity=FindingSeverity.MEDIUM,
        ),
    ]

    output = OperationsSynthesizer().invoke(
        {"specialist_findings": findings}
    )

    assert [finding.priority_rank for finding in output.prioritized_findings] == [
        1,
        2,
        3,
    ]
    assert [finding.severity for finding in output.prioritized_findings] == [
        FindingSeverity.CRITICAL,
        FindingSeverity.MEDIUM,
        FindingSeverity.LOW,
    ]


def test_synthesis_input_rejects_raw_operational_context() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OperationsSynthesisInput(
            specialist_findings=[],
            reservation_context={"res_forbidden": {}},  # type: ignore[call-arg]
        )


def test_synthesizer_is_a_typed_langchain_runnable() -> None:
    synthesizer = OperationsSynthesizer()

    assert synthesizer.runnable.get_input_schema() is OperationsSynthesisInput
    assert synthesizer.runnable.get_output_schema() is OperationsSynthesisOutput
    assert set(OperationsSynthesisInput.model_fields) == {"specialist_findings"}


class RecordingSynthesizer:
    def __init__(self) -> None:
        self.calls: list[SynthesisInvocation] = []
        self.delegate = OperationsSynthesizer()

    def invoke(
        self,
        payload: SynthesisInvocation | dict,
    ) -> OperationsSynthesisOutput:
        context = SynthesisInvocation.model_validate(payload)
        self.calls.append(context)
        return self.delegate.invoke(
            OperationsSynthesisInput(
                specialist_findings=context.specialist_findings,
            )
        )


class FailingSynthesizer:
    def invoke(self, payload: dict) -> OperationsSynthesisOutput:
        raise RuntimeError("synthetic synthesis failure")


def test_phase_5_graph_synthesizes_once_after_all_parallel_specialists() -> None:
    recorder = RecordingSynthesizer()
    graph = build_phase_5_graph(
        reference_date=REFERENCE_DATE,
        synthesis_runner=recorder,
    )

    result = graph.invoke(
        create_initial_state(
            "What needs my attention today?",
            request_id="phase-5-graph",
        )
    )

    assert len(recorder.calls) == 1
    assert {finding.specialist for finding in recorder.calls[0].specialist_findings} == {
        SpecialistName.BOOKING,
        SpecialistName.GUEST,
        SpecialistName.TURNOVER,
        SpecialistName.MAINTENANCE,
    }
    assert recorder.calls[0].date_scope == "2026-08-28"
    assert result["overall_status"] == "needs_attention"
    assert result["operational_findings"]
    assert result["priority_items"]
    assert result["proposed_actions"]
    assert result["action_proposed"] is True
    assert result["final_response"].startswith("Overall status: needs attention")
    assert result["requires_human_review"] is False
    assert result["executed_actions"] == []


def test_phase_5_graph_contains_no_gate_hitl_or_execution_nodes() -> None:
    graph = build_phase_5_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert "operations_synthesizer" in node_names
    assert not {
        "risk_gate",
        "human_review",
        "approve_action",
        "execute_action",
    } & node_names


def test_synthesis_failure_records_error_without_proposing_or_executing_action() -> None:
    graph = build_phase_5_graph(
        reference_date=REFERENCE_DATE,
        synthesis_runner=FailingSynthesizer(),
    )

    result = graph.invoke(
        create_initial_state(
            "What needs my attention today?",
            request_id="phase-5-failure",
        )
    )

    assert result["operational_findings"] == []
    assert result["proposed_actions"] == []
    assert result["action_proposed"] is False
    assert result["executed_actions"] == []
    synthesis_errors = [
        error for error in result["errors"] if error["stage"] == "synthesis_execution"
    ]
    assert len(synthesis_errors) == 1
    assert synthesis_errors[0]["component"] == "operations_synthesizer"
