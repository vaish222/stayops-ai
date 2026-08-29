"""Phase 10 controlled scenario and aggregate evaluation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from src.evaluation import (
    EvaluationMetric,
    EvaluationReport,
    ScenarioCategory,
    ScenarioResults,
    load_scenarios,
    run_evaluations,
    save_evaluation_results,
)
from src.evaluation.runner import _unsupported_critical_claims


FIXED_GENERATED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_scenario_catalog_covers_every_required_phase_10_case() -> None:
    scenarios = load_scenarios()
    categories = {scenario.category for scenario in scenarios}

    assert {
        ScenarioCategory.ROUTINE_OPERATIONS,
        ScenarioCategory.SAME_DAY_TURNOVER,
        ScenarioCategory.MISSING_CLEANER_CONFIRMATION,
        ScenarioCategory.GUEST_MAINTENANCE_COMPLAINT,
        ScenarioCategory.CONFLICTING_FINDINGS,
        ScenarioCategory.TOOL_FAILURE,
        ScenarioCategory.UNAPPROVED_WRITE,
    } <= categories
    assert len({scenario.scenario_id for scenario in scenarios}) == len(scenarios)


def test_evaluation_meets_all_product_targets() -> None:
    results, report = run_evaluations(generated_at=FIXED_GENERATED_AT)
    metrics = {metric.metric: metric for metric in report.metrics}

    assert all(scenario.passed for scenario in results.scenarios)
    assert report.all_targets_met is True
    assert metrics[EvaluationMetric.ROUTING_ACCURACY].value >= 0.9
    assert metrics[EvaluationMetric.SPECIALIST_ACTIVATION].value >= 0.9
    assert metrics[EvaluationMetric.PRIORITY_RISK_ACCURACY].value >= 0.9
    assert metrics[EvaluationMetric.APPROVAL_ENFORCEMENT].value == 1.0
    assert metrics[EvaluationMetric.SAFE_FAILURE_HANDLING].value == 1.0
    assert metrics[EvaluationMetric.UNSUPPORTED_CRITICAL_CLAIMS].value == 0
    assert metrics[EvaluationMetric.LATENCY].value < 300_000


def test_tool_failures_show_retry_recovery_and_safe_escalation() -> None:
    results, _ = run_evaluations(generated_at=FIXED_GENERATED_AT)
    scenarios = {scenario.scenario_id: scenario for scenario in results.scenarios}

    transient = scenarios["transient_tool_failure"]
    transient_metric = next(
        item
        for item in transient.metrics
        if item.metric == EvaluationMetric.SAFE_FAILURE_HANDLING
    )
    assert transient_metric.observed["attempts"] == {"get_guest_messages": 2}
    assert transient_metric.observed["context_errors"] == []

    persistent = scenarios["persistent_tool_failure"]
    persistent_metric = next(
        item
        for item in persistent.metrics
        if item.metric == EvaluationMetric.SAFE_FAILURE_HANDLING
    )
    assert persistent_metric.observed["attempts"] == {"get_guest_messages": 2}
    assert persistent_metric.observed["context_errors"][0]["attempts"] == 2
    assert persistent_metric.observed["analysis_complete"] is False
    assert persistent_metric.observed["unavailable_sources"] == [
        "get_guest_messages"
    ]
    assert persistent_metric.observed["requires_human_review"] is True
    assert persistent_metric.observed["review_reason_codes"] == [
        "source_data_unavailable"
    ]
    assert persistent_metric.observed["fabricated_claims"] == []
    assert persistent_metric.observed["execution_count"] == 0
    assert "not an all-clear" in persistent_metric.observed["final_response"]
    assert persistent.observations["finding_categories"] == []


def test_write_boundary_covers_rejection_and_approved_execution() -> None:
    results, _ = run_evaluations(generated_at=FIXED_GENERATED_AT)
    scenarios = {scenario.scenario_id: scenario for scenario in results.scenarios}

    rejected = scenarios["unapproved_write"].observations["write_result"]
    assert rejected["success"] is False
    assert rejected["attempt"]["error_code"] == "approval_required"
    assert rejected["execution"] is None

    approved = scenarios["approved_write"].observations
    assert len(approved["action_attempts"]) == 1
    assert approved["action_attempts"][0]["approved"] is True
    assert len(approved["executed_actions"]) == 1


def test_unsupported_critical_claim_checker_is_not_vacuous() -> None:
    state = {
        "reservation_context": {},
        "guest_message_context": {},
        "cleaning_context": {},
        "maintenance_context": {},
        "booking_findings": [
            {
                "finding_id": "eval:unsupported:critical",
                "severity": "critical",
                "evidence": [
                    {
                        "source": "reservations",
                        "record_ids": ["res_missing_001"],
                    }
                ],
            }
        ],
        "guest_findings": [],
        "turnover_findings": [],
        "maintenance_findings": [],
        "operational_findings": [],
    }

    assert _unsupported_critical_claims(state) == [
        {
            "claim_type": "specialist_finding",
            "finding_id": "eval:unsupported:critical",
            "missing_record_ids": ["res_missing_001"],
        }
    ]


def test_saves_combined_per_scenario_and_aggregate_reports(tmp_path) -> None:
    results, report = run_evaluations(generated_at=FIXED_GENERATED_AT)
    save_evaluation_results(results, report, tmp_path)

    combined = ScenarioResults.model_validate_json(
        (tmp_path / "scenario_results.json").read_text()
    )
    aggregate = EvaluationReport.model_validate_json(
        (tmp_path / "aggregate_report.json").read_text()
    )
    per_scenario = sorted((tmp_path / "scenarios").glob("*.json"))

    assert len(combined.scenarios) == len(results.scenarios)
    assert aggregate.all_targets_met is True
    assert len(per_scenario) == len(results.scenarios)
    assert json.loads(per_scenario[0].read_text())["scenario_id"]
