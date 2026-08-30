"""Provider comparison aggregation tests."""

from __future__ import annotations

from datetime import UTC, datetime

from src.evaluation import run_evaluations
from src.evaluation.provider_comparison import summarize_provider


def test_deterministic_comparison_summary_aggregates_repeated_runs() -> None:
    first_results, first_report = run_evaluations(
        generated_at=datetime(2026, 8, 29, tzinfo=UTC)
    )
    second_results, second_report = run_evaluations(
        generated_at=datetime(2026, 8, 29, tzinfo=UTC)
    )

    summary = summarize_provider(
        "deterministic",
        [first_results, second_results],
        [first_report, second_report],
    )

    assert summary["evaluation_runs"] == 2
    assert summary["scenario_runs"] == 18
    assert summary["passed_scenario_runs"] == 18
    assert summary["scenario_pass_rate"] == 1.0
    assert summary["synthesis"]["run_count"] == 16
    assert summary["synthesis"]["native_completion_rate"] == 1.0
    assert summary["synthesis"]["fallback_rate"] == 0.0
    assert summary["metric_pass_rates"]["unsupported_critical_claims"] == 1.0
