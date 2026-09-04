"""Run and report the untouched 50-case Week 4 StayOps baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Iterable
from uuid import UUID, uuid4

from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import Client, trace, tracing_context

from src.agents.llm_operations_synthesizer import (
    DeterministicSynthesisRunner,
    LLMOperationsSynthesizer,
)
from src.evaluation.golden_contracts import (
    FROZEN_DATASET_SHA256,
    ComponentScore,
    GoldenActual,
    GoldenCase,
    GoldenCaseResult,
    GoldenDataset,
    GoldenRunResults,
)
from src.evaluation.golden_evaluators import (
    PASS_BARS,
    aggregate_case_results,
    detect_forbidden_claims,
    score_failure_recovery,
    score_required_facts,
    score_routing,
    score_trajectory,
)
from src.graph import build_phase_8_graph, create_initial_state
from src.llm.settings import LLMProvider, LLMSynthesizerFallback
from src.observability import LangSmithSettings, collect_read_tool_calls
from src.tools import FailureSimulator, SimulatedFailureConfig, SimulatedOperationsStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "evaluation" / "week4" / "golden_dataset_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results" / "baseline-v1"
DEFAULT_RUN_VERSION = "baseline-v1"
ROOT_RUN_NAME = "StayOps Golden Evaluation Case"
VALIDATION_CASES = ("STAY-001", "STAY-008", "STAY-023", "STAY-041", "STAY-048")


class _InvalidStructuredOutputModel:
    """Evaluation-only model boundary used solely by STAY-047."""

    def invoke(self, messages: list[Any]) -> dict[str, Any]:
        del messages
        return {"overall_status": "not-a-valid-status", "prioritized_findings": "invalid"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_golden_dataset(
    path: str | Path = DEFAULT_DATASET_PATH,
    *,
    verify_frozen_hash: bool = True,
) -> GoldenDataset:
    """Load the complete v1 dataset and fail if its frozen identity changed."""

    source = Path(path)
    observed_hash = _sha256(source)
    if verify_frozen_hash and observed_hash != FROZEN_DATASET_SHA256:
        raise ValueError(
            "golden_dataset_v1.json does not match the approved frozen SHA-256: "
            f"{observed_hash}"
        )
    return GoldenDataset.model_validate_json(source.read_text(encoding="utf-8"))


def _failure_simulator(case: GoldenCase) -> FailureSimulator | None:
    injection = case.failure_injection
    if injection is None or injection.type != "read_tool":
        return None
    assert injection.tool is not None
    assert injection.failures_before_success is not None
    return FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={
                injection.tool: injection.failures_before_success,
            }
        )
    )


def _synthesis_runner(case: GoldenCase) -> Any:
    injection = case.failure_injection
    if injection is None or injection.type != "llm_synthesizer":
        return DeterministicSynthesisRunner()
    return LLMOperationsSynthesizer(
        structured_model=_InvalidStructuredOutputModel(),
        provider=LLMProvider.NEBIUS,
        model="evaluation-invalid-structured-output",
        fallback=LLMSynthesizerFallback.DETERMINISTIC,
    )


def _langsmith_client(settings: LangSmithSettings) -> Client | None:
    if not settings.enabled:
        return None
    return Client(
        api_key=(
            settings.api_key.get_secret_value()
            if settings.api_key is not None
            else None
        ),
        api_url=settings.endpoint,
        workspace_id=settings.workspace_id,
    )


def _expected_metadata(case: GoldenCase, run_version: str) -> dict[str, Any]:
    expected = case.expected
    return {
        "case_id": case.case_id,
        "dataset_version": case.dataset_version,
        "scenario_type": case.scenario_type,
        "difficulty": case.difficulty,
        "domain": case.domain,
        "run_version": run_version,
        "reference_date": case.reference_date.isoformat(),
        "synthesizer_mode": "deterministic",
        "expected_intent": expected.intent.value,
        "expected_specialists": [item.value for item in expected.required_specialists],
        "expected_human_review": expected.human_review_required,
    }


def _empty_failed_state(case: GoldenCase, exc: Exception) -> dict[str, Any]:
    state = dict(create_initial_state(case.input.query, request_id=f"eval-{case.case_id}"))
    state["errors"] = [
        {
            "stage": "evaluation_execution",
            "code": "workflow_crash",
            "message": str(exc),
            "component": type(exc).__name__,
            "retryable": False,
        }
    ]
    return state


def _actual_from_state(
    state: dict[str, Any],
    tool_attempts: list[dict[str, Any]],
    latency_ms: float,
    run_id: UUID,
) -> GoldenActual:
    attempts = Counter(item["tool_name"] for item in tool_attempts)
    agent_runs = list(state.get("agent_runs", []))
    specialists_run = list(
        dict.fromkeys(item["agent"] for item in agent_runs)
    )
    action_attempts = list(state.get("action_attempts", []))
    write_tools_called = list(
        dict.fromkeys(
            str(item.get("tool_name"))
            for item in action_attempts
            if item.get("tool_name")
        )
    )
    synthesis = state.get("synthesis_run") or {}
    status = state.get("overall_status") or None
    final_response = state.get("final_response") or None
    return GoldenActual(
        actual_intent=state.get("intent", ""),
        actual_property_ids=list(state.get("property_scope", [])),
        actual_date_scope=state.get("date_scope"),
        actual_write_requested=bool(state.get("write_requested")),
        selected_specialists=list(state.get("selected_specialists", [])),
        specialists_actually_run=specialists_run,
        tools_called=list(dict.fromkeys(item["tool_name"] for item in tool_attempts)),
        tool_attempt_counts=dict(attempts),
        unavailable_sources=list(state.get("unavailable_sources", [])),
        analysis_complete=bool(state.get("analysis_complete")),
        synthesis_complete=bool(state.get("synthesis_complete")),
        risk_gate_evaluated=bool(state.get("risk_gate_evaluated")),
        response_generated=bool(state.get("response_generated")),
        workflow_errors=list(state.get("errors", [])),
        agent_runs=agent_runs,
        proposed_actions=list(state.get("proposed_actions", [])),
        human_review_triggered=bool(state.get("requires_human_review")),
        write_tools_called=write_tools_called,
        write_executed=bool(state.get("executed_actions", [])),
        final_response=final_response,
        overall_status=status,
        structured_findings=list(state.get("operational_findings", [])),
        specialist_findings={
            name: list(state.get(f"{name}_findings", []))
            for name in ("booking", "guest", "turnover", "maintenance")
        },
        end_to_end_latency_ms=latency_ms,
        llm_token_usage=None,
        synthesizer_mode=synthesis.get("mode"),
        model_provider=synthesis.get("provider"),
        model=synthesis.get("model"),
        langsmith_trace_id=run_id,
        langsmith_run_id=run_id,
        langsmith_run_url=None,
        interrupted_for_review=bool(state.get("__interrupt__")),
    )


def _evaluate_case(
    case: GoldenCase,
    actual: GoldenActual,
    state: dict[str, Any],
    run_version: str,
) -> GoldenCaseResult:
    scores: dict[str, ComponentScore] = {}
    scores.update(score_routing(case, actual))
    scores.update(score_trajectory(case, actual))
    fact_matches, fact_score = score_required_facts(case, state)
    scores["required_fact_recall"] = fact_score
    if case.expected.overall_status is None:
        status_score = ComponentScore(
            applicable=False,
            details={"expected": None, "actual": actual.overall_status},
        )
    else:
        status_score = ComponentScore(
            applicable=True,
            score=float(actual.overall_status == case.expected.overall_status.value),
            passed=actual.overall_status == case.expected.overall_status.value,
            details={
                "expected": case.expected.overall_status.value,
                "actual": actual.overall_status,
            },
        )
    scores["overall_status_correct"] = status_score
    operational_parts = [
        item.score
        for item in (fact_score, status_score)
        if item.applicable and item.score is not None
    ]
    operational_score = sum(operational_parts) / len(operational_parts) if operational_parts else None
    scores["operational_decision_accuracy"] = (
        ComponentScore(
            applicable=True,
            score=round(operational_score, 4),
            passed=operational_score == 1.0,
        )
        if operational_score is not None
        else ComponentScore(applicable=False)
    )
    review_correct = actual.human_review_triggered == case.expected.human_review_required
    scores["human_review_correct"] = ComponentScore(
        applicable=True,
        score=float(review_correct),
        passed=review_correct,
        details={
            "expected": case.expected.human_review_required,
            "actual": actual.human_review_triggered,
            "false_positive_review": actual.human_review_triggered
            and not case.expected.human_review_required,
            "false_negative_review": not actual.human_review_triggered
            and case.expected.human_review_required,
        },
    )
    unauthorized = actual.write_executed and not case.expected.write_execution_expected
    scores["write_safety"] = ComponentScore(
        applicable=True,
        score=float(not unauthorized),
        passed=not unauthorized,
        details={"unauthorized_write": unauthorized},
    )
    violations, needs_review = detect_forbidden_claims(case, actual, state)
    scores["unsupported_critical_claims"] = ComponentScore(
        applicable=True,
        score=float(not violations),
        passed=not violations,
        details={"violation_count": len(violations)},
    )
    scores["failure_recovery_pass"] = score_failure_recovery(case, actual, state)
    hard_score_names = (
        "intent_correct",
        "property_scope_correct",
        "write_intent_correct",
        "date_scope_correct",
        "operational_decision_accuracy",
        "trajectory_pass",
        "human_review_correct",
        "write_safety",
        "unsupported_critical_claims",
        "failure_recovery_pass",
    )
    case_pass = all(
        scores[name].passed
        for name in hard_score_names
        if scores[name].applicable
    )
    return GoldenCaseResult(
        case_id=case.case_id,
        dataset_version=case.dataset_version,
        run_version=run_version,
        scenario_type=case.scenario_type,
        difficulty=case.difficulty,
        domain=case.domain,
        reference_date=case.reference_date,
        query=case.input.query,
        expected=case.expected,
        actual=actual,
        fact_matches=fact_matches,
        scores=scores,
        forbidden_claim_violations=violations,
        needs_human_or_llm_review=needs_review,
        case_pass=case_pass,
    )


def run_golden_case(
    case: GoldenCase,
    *,
    run_version: str = DEFAULT_RUN_VERSION,
    settings: LangSmithSettings | None = None,
    run_id: UUID | None = None,
) -> GoldenCaseResult:
    """Execute one isolated case without approving or changing production state."""

    configured = settings or LangSmithSettings.from_environment()
    client = _langsmith_client(configured)
    root_id = run_id or uuid4()
    metadata = _expected_metadata(case, run_version)
    simulator = _failure_simulator(case)
    with tempfile.TemporaryDirectory(prefix=f"stayops-{case.case_id.lower()}-") as runtime_dir:
        graph = build_phase_8_graph(
            reference_date=case.reference_date,
            failure_simulator=simulator,
            runtime_store=SimulatedOperationsStore(runtime_dir),
            synthesis_runner=_synthesis_runner(case),
        )
        config = {
            "configurable": {"thread_id": f"{run_version}-{case.case_id}-{root_id}"},
            "run_name": "StayOps Production Workflow",
            "metadata": {"case_id": case.case_id, "run_version": run_version},
        }
        started = perf_counter_ns()
        with tracing_context(
            enabled=configured.enabled,
            project_name=configured.project,
            client=client,
        ):
            with trace(
                ROOT_RUN_NAME,
                run_type="chain",
                inputs={"query": case.input.query},
                tags=[
                    f"case:{case.case_id}",
                    f"dataset:{case.dataset_version}",
                    f"scenario:{case.scenario_type}",
                    f"run:{run_version}",
                ],
                metadata=metadata,
                client=client,
                project_name=configured.project,
                run_id=root_id,
            ) as root:
                with collect_read_tool_calls() as tool_attempts:
                    try:
                        state = graph.invoke(
                            create_initial_state(
                                case.input.query,
                                request_id=f"{run_version}-{case.case_id}",
                            ),
                            config=config,
                        )
                    except Exception as exc:  # A failed case must not abort the dataset run.
                        state = _empty_failed_state(case, exc)
                latency_ms = round((perf_counter_ns() - started) / 1_000_000, 3)
                actual = _actual_from_state(state, tool_attempts, latency_ms, root_id)
                result = _evaluate_case(case, actual, state, run_version)
                root.add_metadata(
                    {
                        "actual_intent": actual.actual_intent,
                        "normalized_operation": state.get("normalized_operation"),
                        "specialist_policy": state.get("selected_specialists", []),
                        "write_intent_detected": bool(state.get("write_requested")),
                        "readiness_detected": bool(state.get("readiness_detected")),
                        "date_normalization_method": state.get(
                            "date_normalization_method"
                        ),
                        "actual_specialists": actual.specialists_actually_run,
                        "actual_human_review": actual.human_review_triggered,
                        "case_pass": result.case_pass,
                        "workflow_error_count": len(actual.workflow_errors),
                    }
                )
                root.end(
                    outputs={
                        "actual": actual.model_dump(mode="json"),
                        "scores": {
                            name: score.model_dump(mode="json")
                            for name, score in result.scores.items()
                        },
                        "case_pass": result.case_pass,
                    }
                )
    if configured.enabled:
        wait_for_all_tracers()
        assert client is not None
        client.flush()
    return result


def _breakdowns(case_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("scenario_type", "domain", "difficulty"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in case_payloads:
            groups[str(case[field])].append(case)
        result[field] = {
            name: aggregate_case_results(items) for name, items in sorted(groups.items())
        }
    return result


def build_summary(results: GoldenRunResults) -> dict[str, Any]:
    payloads = [case.model_dump(mode="json") for case in results.cases]
    metrics = aggregate_case_results(payloads)
    threshold_results = {
        "operational_decision_accuracy": (
            metrics["operational_decision_accuracy"] is not None
            and metrics["operational_decision_accuracy"]
            >= PASS_BARS["operational_decision_accuracy"]
        ),
        "trajectory_correctness": (
            metrics["trajectory_pass_rate"] is not None
            and metrics["trajectory_pass_rate"] >= PASS_BARS["trajectory_correctness"]
        ),
        "hitl_accuracy": (
            metrics["hitl_accuracy"] is not None
            and metrics["hitl_accuracy"] >= PASS_BARS["hitl_accuracy"]
        ),
        "safe_failure_recovery": (
            metrics["safe_failure_recovery"] is not None
            and metrics["safe_failure_recovery"] >= PASS_BARS["safe_failure_recovery"]
        ),
        "p95_latency": metrics["latency_ms"]["p95"] < PASS_BARS["p95_latency_ms"],
        "unauthorized_writes": metrics["unauthorized_write_count"] == 0,
        "unsupported_critical_claims": metrics["unsupported_critical_claim_count"] == 0,
    }
    return {
        "dataset_version": results.dataset_version,
        "run_version": results.run_version,
        "synthesizer_mode": results.synthesizer_mode,
        "dataset_sha256": results.dataset_sha256,
        "generated_at": results.generated_at.isoformat(),
        "metrics": metrics,
        "pass_bars": PASS_BARS,
        "threshold_results": threshold_results,
        "all_thresholds_met": all(threshold_results.values()),
        "breakdowns": _breakdowns(payloads),
    }


def run_golden_dataset(
    cases: Iterable[GoldenCase],
    *,
    run_version: str = DEFAULT_RUN_VERSION,
    settings: LangSmithSettings | None = None,
    generated_at: datetime | None = None,
) -> tuple[GoldenRunResults, dict[str, Any]]:
    configured = settings or LangSmithSettings.from_environment()
    case_results = [
        run_golden_case(case, run_version=run_version, settings=configured)
        for case in cases
    ]
    results = GoldenRunResults(
        dataset_version="v1",
        run_version=run_version,
        synthesizer_mode="deterministic",
        dataset_sha256=FROZEN_DATASET_SHA256,
        generated_at=generated_at or datetime.now(UTC),
        cases=case_results,
    )
    return results, build_summary(results)


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def render_summary_markdown(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    latency = metrics["latency_ms"]
    run_label = (
        "Improved"
        if str(summary["run_version"]).startswith("improved")
        else "Baseline"
    )
    lines = [
        f"# StayOps Week 4 {run_label} Summary",
        "",
        f"Dataset: `{summary['dataset_version']}`  ",
        f"Run: `{summary['run_version']}`  ",
        f"Synthesizer: `{summary['synthesizer_mode']}`  ",
        f"Cases: {metrics['case_count']}",
        "",
        "## Primary metrics",
        "",
        f"- Operational Decision Accuracy: {_format_percent(metrics['operational_decision_accuracy'])}",
        f"- Specialist Recall: {_format_percent(metrics['specialist_recall'])}",
        f"- Specialist Precision: {_format_percent(metrics['specialist_precision'])}",
        f"- Tool Recall: {_format_percent(metrics['tool_recall'])}",
        f"- Tool Precision: {_format_percent(metrics['tool_precision'])}",
        f"- Trajectory Pass Rate: {_format_percent(metrics['trajectory_pass_rate'])}",
        f"- HITL Accuracy: {_format_percent(metrics['hitl_accuracy'])}",
        f"- Safe Failure Recovery: {_format_percent(metrics['safe_failure_recovery'])}",
        "",
        "## Safety guardrails",
        "",
        f"- Unauthorized Writes: {metrics['unauthorized_write_count']}",
        f"- Unsupported Critical Claims: {metrics['unsupported_critical_claim_count']}",
        f"- Cases Requiring Human or LLM Review: {metrics['needs_human_or_llm_review_count']}",
        "",
        "## Latency",
        "",
        f"- Average: {latency['average']:.3f} ms",
        f"- Median: {latency['median']:.3f} ms",
        f"- P95: {latency['p95']:.3f} ms",
        f"- Maximum: {latency['maximum']:.3f} ms",
        "",
        "## Breakdowns",
        "",
    ]
    for group_name, groups in summary["breakdowns"].items():
        lines.extend([f"### {group_name.replace('_', ' ').title()}", ""])
        for name, values in groups.items():
            lines.append(
                f"- {name}: {values['case_pass_count']}/{values['case_count']} cases passed; "
                f"operational accuracy {_format_percent(values['operational_decision_accuracy'])}; "
                f"trajectory {_format_percent(values['trajectory_pass_rate'])}"
            )
        lines.append("")
    lines.extend(
        [
            f"## {run_label} discipline",
            "",
            (
                "These results measure the approved H1–H4 implementation against "
                "the unchanged golden dataset and scoring rules."
                if run_label == "Improved"
                else "These results measure the existing StayOps implementation. "
                "No routing, agent, synthesis, safety, HITL, tool, fixture, or UI "
                "behavior was changed to improve scores."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_failure_cases(results: GoldenRunResults) -> str:
    failed = [case for case in results.cases if not case.case_pass]
    run_label = (
        "Improved"
        if results.run_version.startswith("improved")
        else "Baseline"
    )
    lines = [f"# StayOps Week 4 Failed {run_label} Cases", ""]
    if not failed:
        return "\n".join(lines + ["No cases failed.", ""])
    for case in failed:
        failed_scores = [
            name
            for name, score in case.scores.items()
            if score.applicable and score.passed is False
        ]
        lines.extend(
            [
                f"## {case.case_id}",
                "",
                f"- Query: {case.query}",
                f"- Scenario: {case.scenario_type}",
                f"- Domain: {case.domain}",
                f"- Difficulty: {case.difficulty}",
                f"- Failed checks: {', '.join(failed_scores)}",
                f"- LangSmith trace ID: {case.actual.langsmith_trace_id}",
                "",
            ]
        )
    return "\n".join(lines)


def _csv_row(case: GoldenCaseResult) -> dict[str, Any]:
    def score(name: str) -> Any:
        return case.scores[name].score if case.scores[name].applicable else None

    return {
        "case_id": case.case_id,
        "scenario_type": case.scenario_type,
        "difficulty": case.difficulty,
        "domain": case.domain,
        "query": case.query,
        "expected_intent": case.expected.intent.value,
        "actual_intent": case.actual.actual_intent,
        "expected_property_ids": json.dumps(case.expected.property_ids),
        "actual_property_ids": json.dumps(case.actual.actual_property_ids),
        "expected_date_scope": case.expected.date_scope,
        "actual_date_scope": case.actual.actual_date_scope,
        "expected_write_intent": case.expected.write_intent,
        "actual_write_intent": case.actual.actual_write_requested,
        "expected_specialists": json.dumps(
            [item.value for item in case.expected.required_specialists]
        ),
        "actual_specialists": json.dumps(case.actual.specialists_actually_run),
        "expected_tools": json.dumps([item.value for item in case.expected.required_tools]),
        "actual_tools": json.dumps(case.actual.tools_called),
        "expected_human_review": case.expected.human_review_required,
        "actual_human_review": case.actual.human_review_triggered,
        "analysis_complete": case.actual.analysis_complete,
        "unavailable_sources": json.dumps(case.actual.unavailable_sources),
        "overall_status": case.actual.overall_status,
        "workflow_error_count": len(case.actual.workflow_errors),
        "final_response": case.actual.final_response,
        "routing_accuracy": score("routing_accuracy_case"),
        "required_fact_recall": score("required_fact_recall"),
        "operational_decision_accuracy": score("operational_decision_accuracy"),
        "specialist_recall": score("specialist_recall"),
        "specialist_precision": score("specialist_precision"),
        "tool_recall": score("tool_recall"),
        "tool_precision": score("tool_precision"),
        "trajectory_pass": case.scores["trajectory_pass"].passed,
        "human_review_correct": case.scores["human_review_correct"].passed,
        "failure_recovery_pass": case.scores["failure_recovery_pass"].passed,
        "unauthorized_write": case.scores["write_safety"].details["unauthorized_write"],
        "write_executed": case.actual.write_executed,
        "forbidden_claim_violation_count": len(case.forbidden_claim_violations),
        "needs_human_or_llm_review": case.needs_human_or_llm_review,
        "failed_checks": json.dumps(
            [
                name
                for name, component in case.scores.items()
                if component.applicable and component.passed is False
            ]
        ),
        "latency_ms": case.actual.end_to_end_latency_ms,
        "langsmith_trace_id": str(case.actual.langsmith_trace_id),
        "case_pass": case.case_pass,
    }


def save_results(
    results: GoldenRunResults,
    summary: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary_stem = (
        "improved_summary"
        if results.run_version.startswith("improved")
        else "baseline_summary"
    )
    case_payloads = [case.model_dump(mode="json") for case in results.cases]
    (destination / "case_results.json").write_text(
        json.dumps(case_payloads, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = [_csv_row(case) for case in results.cases]
    with (destination / "case_results.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)
    (destination / f"{summary_stem}.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / f"{summary_stem}.md").write_text(
        render_summary_markdown(summary),
        encoding="utf-8",
    )
    (destination / "failure_cases.md").write_text(
        render_failure_cases(results),
        encoding="utf-8",
    )


def format_validation_case(case: GoldenCaseResult) -> str:
    expected = case.expected
    actual = case.actual
    failure = case.scores["failure_recovery_pass"]
    return "\n".join(
        [
            case.case_id,
            f"  intent: {expected.intent.value} -> {actual.actual_intent}",
            "  specialists: "
            f"{[item.value for item in expected.required_specialists]} -> "
            f"{actual.specialists_actually_run}",
            f"  tools: {[item.value for item in expected.required_tools]} -> {actual.tools_called}",
            f"  HITL: {expected.human_review_required} -> {actual.human_review_triggered}",
            f"  required fact score: {case.scores['required_fact_recall'].score}",
            f"  failure recovery: {failure.passed if failure.applicable else 'N/A'}",
            f"  latency: {actual.end_to_end_latency_ms:.3f} ms",
            f"  LangSmith trace ID: {actual.langsmith_trace_id}",
        ]
    )


def _filter_cases(dataset: GoldenDataset, args: argparse.Namespace) -> list[GoldenCase]:
    cases = dataset.cases
    if args.validation:
        cases = [case for case in cases if case.case_id in VALIDATION_CASES]
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case.case_id in wanted]
    if args.scenario:
        cases = [case for case in cases if case.scenario_type == args.scenario]
    if args.domain:
        cases = [case for case in cases if case.domain == args.domain]
    if args.difficulty:
        cases = [case for case in cases if case.difficulty == args.difficulty]
    if not cases:
        raise ValueError("no golden cases match the supplied filters")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the untouched StayOps Week 4 baseline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case", action="append", help="Run one case ID; may be repeated")
    parser.add_argument("--scenario", choices=("happy_path", "edge", "failure", "adversarial"))
    parser.add_argument("--domain")
    parser.add_argument("--difficulty", choices=("easy", "medium", "hard"))
    parser.add_argument("--run-version", default=DEFAULT_RUN_VERSION)
    parser.add_argument("--validation", action="store_true", help="Run the five evaluator-validation cases")
    parser.add_argument("--no-tracing", action="store_true")
    args = parser.parse_args()

    dataset = load_golden_dataset(args.dataset)
    cases = _filter_cases(dataset, args)
    settings = LangSmithSettings.from_environment()
    if args.no_tracing:
        settings = settings.model_copy(update={"enabled": False})
    results, summary = run_golden_dataset(
        cases,
        run_version=args.run_version,
        settings=settings,
    )
    save_results(results, summary, args.output_dir)
    if args.validation:
        print("\n\n".join(format_validation_case(case) for case in results.cases))
    else:
        metrics = summary["metrics"]
        print(
            f"Cases: {metrics['case_pass_count']}/{metrics['case_count']} passed; "
            f"thresholds met: {summary['all_thresholds_met']}"
        )
        print(f"Results: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
