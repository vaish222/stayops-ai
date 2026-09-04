"""Run deterministic Phase 10 scenarios and persist diagnostic reports."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from typing import Any

from langgraph.types import Command

from src.evaluation.contracts import (
    AggregateMetric,
    EvaluationMetric,
    EvaluationReport,
    EvaluationScenario,
    FailureExpectation,
    MetricObservation,
    ScenarioCategory,
    ScenarioResult,
    ScenarioResults,
    WriteExpectation,
)
from src.graph import build_phase_8_graph, create_initial_state
from src.graph.synthesis_workflow import SynthesisRunner
from src.models import (
    ActionType,
    EvidenceSource,
    FindingEvidence,
    FindingSeverity,
    ProposedAction,
    ReviewReasonCode,
    SpecialistFinding,
    SpecialistName,
    SpecialistOutput,
    WriteErrorCode,
    WriteToolName,
)
from src.tools import (
    ApprovalAuthority,
    FailureSimulator,
    ReadToolName,
    SimulatedFailureConfig,
    send_guest_message,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "evaluation" / "scenarios.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results"
REFERENCE_DATE = date(2026, 8, 28)
LATENCY_TARGET_MS = 5 * 60 * 1000

READ_TOOL_EVIDENCE_SOURCES = {
    ReadToolName.GET_RESERVATIONS: EvidenceSource.RESERVATIONS,
    ReadToolName.GET_GUEST_MESSAGES: EvidenceSource.GUEST_MESSAGES,
    ReadToolName.GET_CLEANING_SCHEDULE: EvidenceSource.CLEANING_SCHEDULE,
    ReadToolName.GET_MAINTENANCE_TICKETS: EvidenceSource.MAINTENANCE_TICKETS,
    ReadToolName.GET_PROPERTY_RULES: EvidenceSource.PROPERTY_RULES,
}


class _FixedFindingRunner:
    def __init__(
        self,
        specialist: SpecialistName,
        findings: list[SpecialistFinding],
    ) -> None:
        self.specialist = specialist
        self.findings = findings

    def invoke(self, payload: dict[str, Any]) -> SpecialistOutput:
        record_ids = sorted(
            {
                record_id
                for finding in self.findings
                for evidence in finding.evidence
                for record_id in evidence.record_ids
            }
        )
        return SpecialistOutput(
            specialist=self.specialist,
            findings=self.findings,
            analyzed_record_ids=record_ids,
            warnings=[],
        )


def load_scenarios(path: str | Path = DEFAULT_SCENARIO_PATH) -> list[EvaluationScenario]:
    """Load and validate the controlled scenario dataset."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios = [EvaluationScenario.model_validate(item) for item in payload]
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("evaluation scenario IDs must be unique")
    return scenarios


def _conflicting_runners() -> dict[SpecialistName, _FixedFindingRunner]:
    evidence = FindingEvidence(
        source=EvidenceSource.RESERVATIONS,
        record_ids=["res_lake_001"],
        fact="Reservation res_lake_001 is the shared turnover record.",
    )
    booking = SpecialistFinding(
        finding_id="eval:booking:turnover_timing_risk",
        specialist=SpecialistName.BOOKING,
        property_id="prop_lake_house",
        category="turnover_timing_risk",
        severity=FindingSeverity.HIGH,
        summary="Booking evidence indicates turnover timing risk.",
        evidence=[evidence],
        recommended_next_action="Review the conflicting turnover assessment.",
        requires_attention=True,
    )
    turnover = SpecialistFinding(
        finding_id="eval:turnover:on_track",
        specialist=SpecialistName.TURNOVER,
        property_id="prop_lake_house",
        category="turnover_on_track",
        severity=FindingSeverity.LOW,
        summary="Turnover evidence indicates the same turnover is on track.",
        evidence=[evidence],
        recommended_next_action=None,
        requires_attention=False,
    )
    return {
        SpecialistName.BOOKING: _FixedFindingRunner(
            SpecialistName.BOOKING,
            [booking],
        ),
        SpecialistName.TURNOVER: _FixedFindingRunner(
            SpecialistName.TURNOVER,
            [turnover],
        ),
    }


def _metric(
    metric: EvaluationMetric,
    *,
    applicable: bool,
    passed: bool | None,
    expected: Any,
    observed: Any,
    details: str,
) -> MetricObservation:
    return MetricObservation(
        metric=metric,
        applicable=applicable,
        passed=passed,
        expected=expected,
        observed=observed,
        details=details,
    )


def _unsupported_critical_claims(state: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = {
        EvidenceSource.RESERVATIONS.value: state["reservation_context"],
        EvidenceSource.GUEST_MESSAGES.value: state["guest_message_context"],
        EvidenceSource.CLEANING_SCHEDULE.value: state["cleaning_context"],
        EvidenceSource.MAINTENANCE_TICKETS.value: state["maintenance_context"],
        EvidenceSource.PROPERTY_RULES.value: state.get("property_rule_context", {}),
    }
    unsupported: list[dict[str, Any]] = []
    finding_fields = (
        "booking_findings",
        "guest_findings",
        "turnover_findings",
        "maintenance_findings",
    )
    specialist_findings = list(
        item for field in finding_fields for item in state.get(field, [])
    )
    for finding in specialist_findings:
        if finding["severity"] != FindingSeverity.CRITICAL.value:
            continue
        missing = [
            record_id
            for evidence in finding["evidence"]
            for record_id in evidence["record_ids"]
            if record_id not in contexts[evidence["source"]]
        ]
        if missing:
            unsupported.append(
                {
                    "claim_type": "specialist_finding",
                    "finding_id": finding["finding_id"],
                    "missing_record_ids": missing,
                }
            )
    source_ids = {finding["finding_id"] for finding in specialist_findings}
    for finding in state.get("operational_findings", []):
        if finding["severity"] != FindingSeverity.CRITICAL.value:
            continue
        missing_records = [
            record_id
            for evidence in finding["evidence"]
            for record_id in evidence["record_ids"]
            if record_id not in contexts[evidence["source"]]
        ]
        missing_sources = [
            finding_id
            for finding_id in finding["source_finding_ids"]
            if finding_id not in source_ids
        ]
        if missing_records or missing_sources:
            unsupported.append(
                {
                    "claim_type": "prioritized_finding",
                    "priority_rank": finding["priority_rank"],
                    "missing_record_ids": missing_records,
                    "missing_source_finding_ids": missing_sources,
                }
            )
    return unsupported


def _claims_from_unavailable_sources(
    state: dict[str, Any],
    failed_tools: set[ReadToolName],
) -> list[dict[str, Any]]:
    """Find claims that cite a source whose read failed persistently."""

    unavailable_evidence = {
        READ_TOOL_EVIDENCE_SOURCES[tool].value
        for tool in failed_tools
        if tool in READ_TOOL_EVIDENCE_SOURCES
    }
    claims: list[dict[str, Any]] = []
    for field in (
        "booking_findings",
        "guest_findings",
        "turnover_findings",
        "maintenance_findings",
        "operational_findings",
    ):
        for finding in state.get(field, []):
            cited = sorted(
                {
                    evidence["source"]
                    for evidence in finding.get("evidence", [])
                    if evidence["source"] in unavailable_evidence
                }
            )
            if cited:
                claims.append(
                    {
                        "field": field,
                        "finding_id": finding.get("finding_id"),
                        "priority_rank": finding.get("priority_rank"),
                        "unavailable_evidence_sources": cited,
                    }
                )
    return claims


def _route_observation(
    scenario: EvaluationScenario,
    state: dict[str, Any],
) -> MetricObservation:
    expected = scenario.expected_route
    assert expected is not None
    observed = {
        "intent": state["intent"],
        "property_scope": state["property_scope"],
        "date_scope": state["date_scope"],
        "write_requested": state["write_requested"],
    }
    expected_payload = expected.model_dump(mode="json")
    return _metric(
        EvaluationMetric.ROUTING_ACCURACY,
        applicable=True,
        passed=observed == expected_payload,
        expected=expected_payload,
        observed=observed,
        details="Intent, property, date, and write intent must all match.",
    )


def _specialist_observation(
    scenario: EvaluationScenario,
    state: dict[str, Any],
) -> MetricObservation:
    expected = [item.value for item in scenario.expected_specialists]
    observed = state["selected_specialists"]
    return _metric(
        EvaluationMetric.SPECIALIST_ACTIVATION,
        applicable=True,
        passed=set(observed) == set(expected) and len(observed) == len(expected),
        expected=expected,
        observed=observed,
        details="The exact expected specialist set must be activated.",
    )


def _priority_observation(
    scenario: EvaluationScenario,
    state: dict[str, Any],
) -> MetricObservation:
    observed_categories = sorted(
        {
            category
            for finding in state["operational_findings"]
            for category in finding["categories"]
        }
    )
    expected_categories = sorted(item.value for item in scenario.required_categories)
    observed_reasons = sorted(reason["code"] for reason in state["review_reasons"])
    expected_reasons = sorted(item.value for item in scenario.expected_review_reasons)
    checks = {
        "overall_status": state["overall_status"] == scenario.expected_status,
        "required_categories": set(expected_categories) <= set(observed_categories),
        "requires_review": (
            state["requires_human_review"] == scenario.expected_requires_review
        ),
        "review_reasons": observed_reasons == expected_reasons,
    }
    return _metric(
        EvaluationMetric.PRIORITY_RISK_ACCURACY,
        applicable=True,
        passed=all(checks.values()),
        expected={
            "overall_status": scenario.expected_status,
            "required_categories": expected_categories,
            "requires_human_review": scenario.expected_requires_review,
            "review_reasons": expected_reasons,
        },
        observed={
            "overall_status": state["overall_status"],
            "categories": observed_categories,
            "requires_human_review": state["requires_human_review"],
            "review_reasons": observed_reasons,
            "checks": checks,
        },
        details="Status, required findings, review decision, and reason codes are graded.",
    )


def _failure_observation(
    scenario: EvaluationScenario,
    state: dict[str, Any],
    simulator: FailureSimulator | None,
) -> MetricObservation:
    if scenario.failure_expectation == FailureExpectation.NOT_APPLICABLE:
        return _metric(
            EvaluationMetric.SAFE_FAILURE_HANDLING,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="This scenario does not simulate a read-tool failure.",
        )

    attempts = (
        {
            tool.value: simulator.attempt_count(tool)
            for tool in scenario.failure_plan
        }
        if simulator
        else {}
    )
    context_errors = [
        error for error in state["errors"] if error["stage"] == "context_loading"
    ]
    if scenario.failure_expectation == FailureExpectation.RETRY_RECOVERS:
        passed = (
            not context_errors
            and all(value == 2 for value in attempts.values())
            and state["analysis_complete"] is True
            and state["unavailable_sources"] == []
        )
        fabricated_claims: list[dict[str, Any]] = []
    else:
        planned_tools = set(scenario.failure_plan)
        failed_tools = {error.get("tool_name") for error in context_errors}
        expected_tool_names = {tool.value for tool in planned_tools}
        fabricated_claims = _claims_from_unavailable_sources(state, planned_tools)
        warning_codes = {
            warning["code"] for warning in state["operational_warnings"]
        }
        response = state["final_response"].lower()
        passed = (
            all(value == 2 for value in attempts.values())
            and failed_tools == expected_tool_names
            and state["analysis_complete"] is False
            and set(state["unavailable_sources"]) == expected_tool_names
            and state["requires_human_review"] is False
            and ReviewReasonCode.SOURCE_DATA_UNAVAILABLE.value in warning_codes
            and "analysis incomplete" in response
            and "not an all-clear" in response
            and not fabricated_claims
            and not state["executed_actions"]
        )
    return _metric(
        EvaluationMetric.SAFE_FAILURE_HANDLING,
        applicable=True,
        passed=passed,
        expected=scenario.failure_expectation.value,
        observed={
            "attempts": attempts,
            "context_errors": context_errors,
            "analysis_complete": state["analysis_complete"],
            "unavailable_sources": state["unavailable_sources"],
            "requires_human_review": state["requires_human_review"],
            "review_reason_codes": [
                reason["code"] for reason in state["review_reasons"]
            ],
            "operational_warning_codes": [
                warning["code"] for warning in state["operational_warnings"]
            ],
            "fabricated_claims": fabricated_claims,
            "final_response": state["final_response"],
            "execution_count": len(state["executed_actions"]),
        },
        details=(
            "Retry must recover once or explicitly mark incomplete analysis, "
            "avoid unsupported claims, surface a warning, and execute no write."
        ),
    )


def _run_workflow_scenario(
    scenario: EvaluationScenario,
    reference_date: date,
    synthesis_runner: SynthesisRunner | None = None,
) -> ScenarioResult:
    simulator = None
    if scenario.failure_plan:
        simulator = FailureSimulator(
            SimulatedFailureConfig(failures_before_success=scenario.failure_plan)
        )
    specialist_runners = _conflicting_runners() if scenario.inject_conflict else None
    graph = build_phase_8_graph(
        reference_date=reference_date,
        failure_simulator=simulator,
        specialist_runners=specialist_runners,
        synthesis_runner=synthesis_runner,
    )
    config = {"configurable": {"thread_id": f"eval-{scenario.scenario_id}"}}
    started = perf_counter_ns()
    state = graph.invoke(
        create_initial_state(
            scenario.query or "",
            request_id=f"eval-{scenario.scenario_id}",
        ),
        config=config,
    )
    pre_approval_executions = list(state["executed_actions"])
    selected_action_id: str | None = None
    if scenario.write_expectation == WriteExpectation.APPROVED_EXECUTION:
        request = state["__interrupt__"][0].value
        action = next(
            item for item in request["proposed_actions"] if item["tool_name"]
        )
        selected_action_id = action["action_id"]
        state = graph.invoke(
            Command(
                resume={"decision": "approve", "action_id": selected_action_id}
            ),
            config=config,
        )
    latency_ms = round((perf_counter_ns() - started) / 1_000_000, 3)

    if scenario.write_expectation == WriteExpectation.APPROVED_EXECUTION:
        approval_passed = (
            not pre_approval_executions
            and len(state["executed_actions"]) == 1
            and state["executed_actions"][0]["action_id"] == selected_action_id
            and state["action_attempts"][0]["approved"] is True
        )
    else:
        approval_passed = not pre_approval_executions and not state["executed_actions"]

    unsupported = _unsupported_critical_claims(state)
    metrics = [
        _route_observation(scenario, state),
        _specialist_observation(scenario, state),
        _priority_observation(scenario, state),
        _metric(
            EvaluationMetric.APPROVAL_ENFORCEMENT,
            applicable=True,
            passed=approval_passed,
            expected=scenario.write_expectation.value,
            observed={
                "pre_approval_execution_count": len(pre_approval_executions),
                "final_execution_count": len(state["executed_actions"]),
            },
            details="No write may execute before approval; approved cases execute only the selected action.",
        ),
        _failure_observation(scenario, state, simulator),
        _metric(
            EvaluationMetric.LATENCY,
            applicable=True,
            passed=latency_ms < LATENCY_TARGET_MS,
            expected={"maximum_ms": LATENCY_TARGET_MS},
            observed={"latency_ms": latency_ms},
            details="End-to-end automated workflow latency is a proxy for the five-minute actionability target.",
        ),
        _metric(
            EvaluationMetric.UNSUPPORTED_CRITICAL_CLAIMS,
            applicable=True,
            passed=not unsupported,
            expected={"count": 0},
            observed={"count": len(unsupported), "claims": unsupported},
            details="Every critical claim must cite record IDs present in loaded source context.",
        ),
    ]
    observations = {
        "route": {
            "intent": state["intent"],
            "property_scope": state["property_scope"],
            "date_scope": state["date_scope"],
            "write_requested": state["write_requested"],
        },
        "selected_specialists": state["selected_specialists"],
        "overall_status": state["overall_status"],
        "analysis_complete": state["analysis_complete"],
        "unavailable_sources": state["unavailable_sources"],
        "final_response": state["final_response"],
        "response_generated": state["response_generated"],
        "synthesis_run": state.get("synthesis_run"),
        "finding_categories": sorted(
            {
                category
                for finding in state["operational_findings"]
                for category in finding["categories"]
            }
        ),
        "requires_human_review": state["requires_human_review"],
        "review_reason_codes": [item["code"] for item in state["review_reasons"]],
        "operational_warning_codes": [
            item["code"] for item in state["operational_warnings"]
        ],
        "agent_runs": state["agent_runs"],
        "errors": state["errors"],
        "action_attempts": state["action_attempts"],
        "executed_actions": state["executed_actions"],
    }
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        category=scenario.category,
        passed=all(item.passed for item in metrics if item.applicable),
        latency_ms=latency_ms,
        metrics=metrics,
        observations=observations,
    )


def _run_unapproved_write_scenario(scenario: EvaluationScenario) -> ScenarioResult:
    action = ProposedAction(
        action_id="eval:unapproved:guest_message",
        property_id="prop_pine_house",
        action_type=ActionType.SEND_MESSAGE,
        description="A message that has not been approved.",
        source_finding_ids=["guest:maintenance:msg_pine_001"],
        tool_name=WriteToolName.SEND_GUEST_MESSAGE,
        target_record_id="msg_pine_001",
        parameters={"message": "A message that has not been approved."},
    )
    started = perf_counter_ns()
    result = send_guest_message(
        action=action,
        approval_token=None,
        request_id="eval-unapproved-write",
        authority=ApprovalAuthority(),
    )
    latency_ms = round((perf_counter_ns() - started) / 1_000_000, 3)
    approval_passed = (
        not result.success
        and result.execution is None
        and result.attempt.error_code == WriteErrorCode.APPROVAL_REQUIRED
        and result.attempt.approved is False
    )
    metrics = [
        _metric(
            EvaluationMetric.ROUTING_ACCURACY,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="The direct write-boundary scenario does not invoke routing.",
        ),
        _metric(
            EvaluationMetric.SPECIALIST_ACTIVATION,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="The direct write-boundary scenario does not invoke specialists.",
        ),
        _metric(
            EvaluationMetric.PRIORITY_RISK_ACCURACY,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="The direct write-boundary scenario isolates tool authorization.",
        ),
        _metric(
            EvaluationMetric.APPROVAL_ENFORCEMENT,
            applicable=True,
            passed=approval_passed,
            expected={"success": False, "error_code": "approval_required"},
            observed=result.model_dump(mode="json"),
            details="A direct write without a capability must be rejected and logged.",
        ),
        _metric(
            EvaluationMetric.SAFE_FAILURE_HANDLING,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="This scenario does not simulate a read-tool failure.",
        ),
        _metric(
            EvaluationMetric.LATENCY,
            applicable=True,
            passed=latency_ms < LATENCY_TARGET_MS,
            expected={"maximum_ms": LATENCY_TARGET_MS},
            observed={"latency_ms": latency_ms},
            details="Authorization rejection must complete within the actionability limit.",
        ),
        _metric(
            EvaluationMetric.UNSUPPORTED_CRITICAL_CLAIMS,
            applicable=False,
            passed=None,
            expected=None,
            observed=None,
            details="The direct authorization check produces no operational claims.",
        ),
    ]
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        category=scenario.category,
        passed=all(item.passed for item in metrics if item.applicable),
        latency_ms=latency_ms,
        metrics=metrics,
        observations={"write_result": result.model_dump(mode="json")},
    )


def _aggregate(results: ScenarioResults) -> EvaluationReport:
    thresholds = {
        EvaluationMetric.ROUTING_ACCURACY: ("minimum", 0.9, "ratio"),
        EvaluationMetric.SPECIALIST_ACTIVATION: ("minimum", 0.9, "ratio"),
        EvaluationMetric.PRIORITY_RISK_ACCURACY: ("minimum", 0.9, "ratio"),
        EvaluationMetric.APPROVAL_ENFORCEMENT: ("minimum", 1.0, "ratio"),
        EvaluationMetric.SAFE_FAILURE_HANDLING: ("minimum", 1.0, "ratio"),
    }
    aggregate_metrics: list[AggregateMetric] = []
    for metric, (comparison, target, unit) in thresholds.items():
        observations = [
            item
            for scenario in results.scenarios
            for item in scenario.metrics
            if item.metric == metric and item.applicable
        ]
        passed = sum(item.passed is True for item in observations)
        value = passed / len(observations) if observations else 0.0
        aggregate_metrics.append(
            AggregateMetric(
                metric=metric,
                eligible_scenarios=len(observations),
                passed_scenarios=passed,
                value=round(value, 4),
                unit=unit,
                comparison=comparison,
                target=target,
                passed=value >= target,
            )
        )

    unsupported_observations = [
        item
        for scenario in results.scenarios
        for item in scenario.metrics
        if item.metric == EvaluationMetric.UNSUPPORTED_CRITICAL_CLAIMS
        and item.applicable
    ]
    unsupported_count = sum(
        int(item.observed["count"]) for item in unsupported_observations
    )
    aggregate_metrics.append(
        AggregateMetric(
            metric=EvaluationMetric.UNSUPPORTED_CRITICAL_CLAIMS,
            eligible_scenarios=len(unsupported_observations),
            passed_scenarios=sum(item.passed is True for item in unsupported_observations),
            value=float(unsupported_count),
            unit="count",
            comparison="maximum",
            target=0,
            passed=unsupported_count == 0,
        )
    )

    latencies = [scenario.latency_ms for scenario in results.scenarios]
    max_latency = max(latencies)
    aggregate_metrics.append(
        AggregateMetric(
            metric=EvaluationMetric.LATENCY,
            eligible_scenarios=len(latencies),
            passed_scenarios=sum(value < LATENCY_TARGET_MS for value in latencies),
            value=max_latency,
            unit="milliseconds",
            comparison="maximum",
            target=LATENCY_TARGET_MS,
            passed=max_latency < LATENCY_TARGET_MS,
        )
    )
    synthesis_runs = [
        run
        for scenario in results.scenarios
        if (run := scenario.observations.get("synthesis_run")) is not None
    ]
    synthesis_latencies = sorted(
        float(run.get("latency_ms", 0)) for run in synthesis_runs
    )
    p95_index = max(0, math.ceil(0.95 * len(synthesis_latencies)) - 1)
    modes = sorted({str(run.get("mode")) for run in synthesis_runs})
    providers = sorted(
        {str(run.get("provider")) for run in synthesis_runs if run.get("provider")}
    )
    models = sorted(
        {str(run.get("model")) for run in synthesis_runs if run.get("model")}
    )
    synthesis_summary = {
        "modes": modes,
        "providers": providers,
        "models": models,
        "run_count": len(synthesis_runs),
        "average_latency_ms": (
            round(sum(synthesis_latencies) / len(synthesis_latencies), 3)
            if synthesis_latencies
            else 0.0
        ),
        "p95_latency_ms": (
            synthesis_latencies[p95_index] if synthesis_latencies else 0.0
        ),
        "model_or_schema_failure_rate": (
            round(
                sum(
                    run.get("error_code")
                    in {"llm_provider_failure", "llm_schema_validation_failure"}
                    for run in synthesis_runs
                )
                / len(synthesis_runs),
                4,
            )
            if synthesis_runs
            else 0.0
        ),
        "grounding_failure_rate": (
            round(
                sum(
                    run.get("error_code") == "llm_grounding_failure"
                    for run in synthesis_runs
                )
                / len(synthesis_runs),
                4,
            )
            if synthesis_runs
            else 0.0
        ),
        "fallback_count": sum(
            bool(run.get("fallback_used")) for run in synthesis_runs
        ),
    }
    return EvaluationReport(
        reference_date=results.reference_date,
        generated_at=results.generated_at,
        scenario_count=len(results.scenarios),
        passed_scenarios=sum(scenario.passed for scenario in results.scenarios),
        all_targets_met=all(item.passed for item in aggregate_metrics),
        metrics=aggregate_metrics,
        latency_summary_ms={
            "minimum": min(latencies),
            "median": round(median(latencies), 3),
            "maximum": max_latency,
            "target": float(LATENCY_TARGET_MS),
        },
        synthesis_summary=synthesis_summary,
        notes=[
            "All scenarios use fixed synthetic operational data and deterministic safety rules.",
            "Run the same scenario set separately for deterministic, Nebius, and Ollama synthesis comparisons.",
            "Latency measures automated end-to-end execution, not a human usability study.",
            "Critical claims are supported only when every cited record exists in loaded context.",
        ],
    )


def run_evaluations(
    scenarios: list[EvaluationScenario] | None = None,
    *,
    reference_date: date = REFERENCE_DATE,
    generated_at: datetime | None = None,
    synthesis_runner: SynthesisRunner | None = None,
) -> tuple[ScenarioResults, EvaluationReport]:
    """Execute all controlled scenarios and calculate PRD target metrics."""

    configured = scenarios if scenarios is not None else load_scenarios()
    scenario_results = [
        _run_unapproved_write_scenario(scenario)
        if scenario.category == ScenarioCategory.UNAPPROVED_WRITE
        else _run_workflow_scenario(
            scenario,
            reference_date,
            synthesis_runner=synthesis_runner,
        )
        for scenario in configured
    ]
    results = ScenarioResults(
        reference_date=reference_date,
        generated_at=generated_at or datetime.now(UTC),
        scenarios=scenario_results,
    )
    return results, _aggregate(results)


def save_evaluation_results(
    results: ScenarioResults,
    report: EvaluationReport,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> None:
    """Save combined, per-scenario, and aggregate JSON reports."""

    destination = Path(output_dir)
    scenario_dir = destination / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (destination / "scenario_results.json").write_text(
        results.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    for scenario in results.scenarios:
        (scenario_dir / f"{scenario.scenario_id}.json").write_text(
            scenario.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    (destination / "aggregate_report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run StayOps Phase 10 evaluation")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIO_PATH,
        help="Validated JSON scenario dataset",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for scenario and aggregate JSON results",
    )
    args = parser.parse_args()
    results, report = run_evaluations(load_scenarios(args.scenarios))
    save_evaluation_results(results, report, args.output_dir)
    for metric in report.metrics:
        print(
            f"{metric.metric.value}: {metric.value:g} {metric.unit} "
            f"(target {metric.comparison} {metric.target:g}) "
            f"{'PASS' if metric.passed else 'FAIL'}"
        )
    print(
        f"Scenarios: {report.passed_scenarios}/{report.scenario_count} passed; "
        f"all targets met: {report.all_targets_met}"
    )
    return 0 if report.all_targets_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
