"""Run the untouched STAY-001 baseline as one observable LangSmith trace."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any
from uuid import UUID, uuid4

from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import Client, tracing_context

from src.agents.llm_operations_synthesizer import DeterministicSynthesisRunner
from src.evaluation.langsmith_contracts import (
    LangSmithActualBehavior,
    LangSmithBaselineResult,
    LangSmithEvaluationCase,
)
from src.graph import build_phase_8_graph, create_initial_state
from src.observability import LangSmithSettings, collect_read_tool_calls


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE_PATH = PROJECT_ROOT / "evaluation" / "week4" / "stay_001.json"
DEFAULT_RESULT_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "results"
    / "langsmith"
    / "stay_001_baseline.json"
)
ROOT_RUN_NAME = "StayOps Evaluation Run"


def load_langsmith_case(
    path: str | Path = DEFAULT_CASE_PATH,
) -> LangSmithEvaluationCase:
    """Load the one Week 4 case without changing the Phase 10 dataset."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return LangSmithEvaluationCase.model_validate(payload)


def build_trace_config(
    case: LangSmithEvaluationCase,
    run_id: UUID,
) -> dict[str, Any]:
    """Keep immutable expectations in metadata and actuals in run outputs."""

    expected = case.expected
    return {
        "configurable": {
            "thread_id": f"langsmith-{case.case_id.lower()}-{run_id}",
        },
        "run_name": ROOT_RUN_NAME,
        "run_id": run_id,
        "tags": [
            f"case:{case.case_id}",
            f"dataset:{case.dataset_version}",
            f"scenario:{case.scenario_type}",
            f"run:{case.run_version}",
            "synthesizer:deterministic",
        ],
        "metadata": {
            "case_id": case.case_id,
            "dataset_version": case.dataset_version,
            "scenario_type": case.scenario_type,
            "run_version": case.run_version,
            "reference_date": case.reference_date.isoformat(),
            "synthesizer_mode": "deterministic",
            "model_provider": None,
            "model": None,
            "expected_intent": expected.intent,
            "expected_property_scope": expected.property_scope,
            "expected_property_ids": expected.property_ids,
            "expected_date_expression": expected.date_expression,
            "expected_date_scope": expected.resolved_date_scope,
            "expected_specialists": expected.specialists,
            "expected_human_review": expected.human_review,
        },
    }


def _actual_behavior(
    state: dict[str, Any],
    tool_attempts: list[dict[str, Any]],
    latency_ms: float,
) -> LangSmithActualBehavior:
    synthesis = state.get("synthesis_run") or {}
    tools_called = list(
        dict.fromkeys(attempt["tool_name"] for attempt in tool_attempts)
    )
    return LangSmithActualBehavior(
        predicted_intent=state["intent"],
        resolved_property_ids=state["property_scope"],
        resolved_date_scope=state["date_scope"],
        activated_specialists=state["selected_specialists"],
        tools_called=tools_called,
        tool_attempts=tool_attempts,
        human_review_triggered=state["requires_human_review"],
        workflow_errors=state["errors"],
        synthesizer_mode=synthesis.get("mode"),
        model_provider=synthesis.get("provider"),
        model=synthesis.get("model"),
        response_generated=state["response_generated"],
        outcome="interrupted" if state.get("__interrupt__") else "completed",
        end_to_end_latency_ms=latency_ms,
    )


def _comparisons(
    case: LangSmithEvaluationCase,
    actual: LangSmithActualBehavior,
) -> dict[str, bool]:
    expected = case.expected
    return {
        "intent": actual.predicted_intent == expected.intent,
        "date_scope": (
            actual.resolved_date_scope == expected.resolved_date_scope
        ),
        "property_scope": (
            actual.resolved_property_ids == expected.property_ids
        ),
        "specialists": actual.activated_specialists == expected.specialists,
        "human_review": (
            actual.human_review_triggered == expected.human_review
        ),
    }


def run_langsmith_case(
    case: LangSmithEvaluationCase,
    *,
    settings: LangSmithSettings | None = None,
    run_id: UUID | None = None,
    generated_at: datetime | None = None,
    graph: Any | None = None,
) -> LangSmithBaselineResult:
    """Run STAY-001 unchanged and return an expected-versus-actual record."""

    configured = settings or LangSmithSettings.from_environment()
    root_run_id = run_id or uuid4()
    configured_graph = graph or build_phase_8_graph(
        reference_date=case.reference_date,
        synthesis_runner=DeterministicSynthesisRunner(),
    )
    trace_config = build_trace_config(case, root_run_id)
    request_id = f"langsmith-{case.case_id.lower()}-{root_run_id}"
    langsmith_client = (
        Client(
            api_key=(
                configured.api_key.get_secret_value()
                if configured.api_key is not None
                else None
            ),
            api_url=configured.endpoint,
            workspace_id=configured.workspace_id,
        )
        if configured.enabled
        else None
    )

    started_at = perf_counter_ns()
    try:
        with tracing_context(
            enabled=configured.enabled,
            project_name=configured.project,
            client=langsmith_client,
        ):
            with collect_read_tool_calls() as tool_attempts:
                state = configured_graph.invoke(
                    create_initial_state(case.query, request_id=request_id),
                    config=trace_config,
                )
        latency_ms = round((perf_counter_ns() - started_at) / 1_000_000, 3)
    finally:
        if configured.enabled:
            wait_for_all_tracers()
            assert langsmith_client is not None
            langsmith_client.flush()

    actual = _actual_behavior(state, tool_attempts, latency_ms)
    comparisons = _comparisons(case, actual)
    return LangSmithBaselineResult(
        case_id=case.case_id,
        generated_at=generated_at or datetime.now(UTC),
        tracing_enabled=configured.enabled,
        project=configured.project,
        run_id=root_run_id,
        trace_id=root_run_id,
        expected=case.expected,
        actual=actual,
        comparisons=comparisons,
        all_expectations_met=all(comparisons.values()),
    )


def save_langsmith_result(
    result: LangSmithBaselineResult,
    path: str | Path = DEFAULT_RESULT_PATH,
) -> None:
    """Persist trace identifiers and the concise baseline comparison."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def format_summary(result: LangSmithBaselineResult) -> str:
    """Render a concise local report without treating mismatches as errors."""

    expected = result.expected
    actual = result.actual
    rows = [
        ("intent", "Intent", expected.intent, actual.predicted_intent),
        (
            "date_scope",
            "Date scope",
            expected.resolved_date_scope,
            actual.resolved_date_scope or "none",
        ),
        (
            "property_scope",
            "Property IDs",
            expected.property_ids,
            actual.resolved_property_ids,
        ),
        (
            "specialists",
            "Specialists",
            expected.specialists,
            actual.activated_specialists,
        ),
        (
            "human_review",
            "Human review",
            expected.human_review,
            actual.human_review_triggered,
        ),
    ]
    lines = [
        f"{result.case_id} · untouched baseline",
        f"LangSmith project: {result.project}",
        f"Tracing enabled: {str(result.tracing_enabled).lower()}",
        f"Run ID: {result.run_id}",
        f"Trace ID: {result.trace_id}",
        "Expected vs actual:",
    ]
    for comparison_key, label, expected_value, actual_value in rows:
        passed = result.comparisons[comparison_key]
        lines.append(
            f"  {'PASS' if passed else 'FAIL'} {label}: "
            f"expected {expected_value!r}; actual {actual_value!r}"
        )
    lines.extend(
        [
            f"Tools called: {', '.join(actual.tools_called) or 'none'}",
            f"Workflow outcome: {actual.outcome}",
            f"Response generated: {str(actual.response_generated).lower()}",
            f"Workflow errors: {len(actual.workflow_errors)}",
            f"End-to-end latency: {actual.end_to_end_latency_ms:g} ms",
            "Baseline expectations met: "
            f"{str(result.all_expectations_met).lower()}",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trace the untouched STAY-001 baseline in LangSmith",
    )
    parser.add_argument(
        "--case",
        type=Path,
        default=DEFAULT_CASE_PATH,
        help="STAY-001 JSON case file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULT_PATH,
        help="Local expected-versus-actual result JSON",
    )
    args = parser.parse_args()

    settings = LangSmithSettings.from_environment()
    if not settings.enabled:
        parser.error(
            "LANGSMITH_TRACING must be true for the LangSmith baseline runner"
        )
    case = load_langsmith_case(args.case)
    result = run_langsmith_case(case, settings=settings)
    save_langsmith_result(result, args.output)
    print(format_summary(result))
    print(f"Local result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
