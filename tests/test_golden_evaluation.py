"""Week 4 golden baseline contracts, evaluators, isolation, and reporting."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from src.evaluation.golden_contracts import FROZEN_DATASET_SHA256
from src.evaluation.golden_evaluators import (
    _set_scores,
    aggregate_case_results,
    percentile_95,
)
from src.evaluation.golden_runner import (
    VALIDATION_CASES,
    build_summary,
    format_validation_case,
    load_golden_dataset,
    render_failure_cases,
    render_summary_markdown,
    run_golden_case,
    save_results,
)
from src.observability import LangSmithSettings


DISABLED_TRACING = LangSmithSettings(enabled=False)


def _case(case_id: str):
    return next(case for case in load_golden_dataset().cases if case.case_id == case_id)


def test_frozen_dataset_has_the_approved_identity_and_complete_distribution() -> None:
    dataset = load_golden_dataset()

    assert len(dataset.cases) == 50
    assert dataset.scenario_distribution.model_dump() == {
        "happy_path": 25,
        "edge": 15,
        "failure": 7,
        "adversarial": 3,
        "total": 50,
    }
    assert FROZEN_DATASET_SHA256 == (
        "b12b4e0460c521a021293178ec5414ccf6567c3778270f414d56431987ab5a97"
    )


def test_frozen_hash_rejects_a_changed_dataset(tmp_path: Path) -> None:
    changed = tmp_path / "golden_dataset_v1.json"
    changed.write_text('{"changed": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="frozen SHA-256"):
        load_golden_dataset(changed)


@pytest.mark.parametrize(
    ("required", "allowed", "actual", "recall", "precision", "missing", "extra"),
    [
        (["booking"], ["booking"], ["booking"], 1.0, 1.0, [], []),
        (["booking"], ["booking", "turnover"], ["turnover"], 0.0, 1.0, ["booking"], []),
        (["booking"], ["booking"], ["booking", "guest"], 1.0, 0.5, [], ["guest"]),
        ([], [], [], 1.0, 1.0, [], []),
        ([], [], ["guest"], 1.0, 0.0, [], ["guest"]),
    ],
)
def test_required_and_allowed_set_scoring(
    required,
    allowed,
    actual,
    recall,
    precision,
    missing,
    extra,
) -> None:
    recall_score, precision_score, observed_missing, observed_extra = _set_scores(
        required,
        allowed,
        actual,
    )

    assert recall_score.score == recall
    assert precision_score.score == precision
    assert observed_missing == missing
    assert observed_extra == extra


def test_percentile_95_uses_nearest_rank() -> None:
    assert percentile_95([]) == 0.0
    assert percentile_95([1.0]) == 1.0
    assert percentile_95(list(range(1, 21))) == 19


def test_stay_001_matches_the_improved_minimal_trajectory() -> None:
    result = run_golden_case(
        _case("STAY-001"),
        settings=DISABLED_TRACING,
        run_id=UUID("11111111-2222-3333-4444-555555555555"),
    )

    assert result.expected.intent.value == "booking_operations"
    assert result.actual.actual_intent == "booking_operations"
    assert result.scores["required_fact_recall"].score == 1.0
    assert result.scores["specialist_precision"].score == 1.0
    assert result.scores["tool_precision"].score == 1.0
    assert result.scores["human_review_correct"].passed is True
    assert result.case_pass is True


def test_retry_case_records_two_attempts_and_safe_recovery() -> None:
    result = run_golden_case(_case("STAY-041"), settings=DISABLED_TRACING)

    assert result.actual.tool_attempt_counts["get_reservations"] == 2
    assert result.actual.analysis_complete is True
    assert result.actual.unavailable_sources == []
    assert result.scores["failure_recovery_pass"].passed is True


def test_adversarial_write_case_pauses_without_execution() -> None:
    result = run_golden_case(_case("STAY-048"), settings=DISABLED_TRACING)

    assert result.actual.human_review_triggered is True
    assert result.actual.interrupted_for_review is True
    assert result.actual.write_tools_called == []
    assert result.actual.write_executed is False
    assert result.scores["write_safety"].passed is True
    assert result.scores["human_review_correct"].passed is True


def test_invalid_llm_output_uses_evaluation_only_deterministic_fallback() -> None:
    result = run_golden_case(_case("STAY-047"), settings=DISABLED_TRACING)

    assert result.actual.synthesizer_mode == "llm"
    assert result.actual.model_provider == "nebius"
    assert result.actual.model == "evaluation-invalid-structured-output"
    assert result.scores["failure_recovery_pass"].passed is True
    assert result.actual.llm_token_usage is None


@pytest.mark.parametrize("case_id", ["STAY-045", "STAY-049"])
def test_incomplete_not_all_clear_response_is_not_a_readiness_claim(case_id: str) -> None:
    result = run_golden_case(_case(case_id), settings=DISABLED_TRACING)

    assert "not an all-clear" in (result.actual.final_response or "")
    assert result.forbidden_claim_violations == []


def test_case_runs_do_not_change_the_repository_runtime_overlay() -> None:
    runtime_dir = Path("data/runtime")
    before = {
        path.name: path.read_bytes()
        for path in runtime_dir.glob("*.json")
    }

    first = run_golden_case(_case("STAY-048"), settings=DISABLED_TRACING)
    second = run_golden_case(_case("STAY-050"), settings=DISABLED_TRACING)

    after = {path.name: path.read_bytes() for path in runtime_dir.glob("*.json")}
    assert first.actual.write_executed is False
    assert second.actual.write_executed is False
    assert after == before


def test_empty_required_facts_are_not_awarded_an_artificial_score() -> None:
    result = run_golden_case(_case("STAY-027"), settings=DISABLED_TRACING)

    assert result.fact_matches == []
    assert result.scores["required_fact_recall"].applicable is False
    assert result.scores["required_fact_recall"].score is None
    assert result.needs_human_or_llm_review is True


def test_aggregate_preserves_nulls_and_counts_hard_guardrails() -> None:
    first = run_golden_case(_case("STAY-001"), settings=DISABLED_TRACING)
    second = run_golden_case(_case("STAY-048"), settings=DISABLED_TRACING)
    payloads = [first.model_dump(mode="json"), second.model_dump(mode="json")]

    aggregate = aggregate_case_results(payloads)

    assert aggregate["case_count"] == 2
    assert aggregate["unauthorized_write_count"] == 0
    assert aggregate["latency_ms"]["p95"] >= aggregate["latency_ms"]["median"]


def test_reports_include_required_files_and_human_readable_sections(tmp_path: Path) -> None:
    case = run_golden_case(_case("STAY-027"), settings=DISABLED_TRACING)
    from src.evaluation.golden_contracts import GoldenRunResults

    results = GoldenRunResults(
        dataset_version="v1",
        run_version="baseline-v1",
        synthesizer_mode="deterministic",
        dataset_sha256=FROZEN_DATASET_SHA256,
        generated_at=datetime(2026, 9, 3, tzinfo=UTC),
        cases=[case],
    )
    summary = build_summary(results)

    save_results(results, summary, tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == {
        "case_results.json",
        "case_results.csv",
        "baseline_summary.json",
        "baseline_summary.md",
        "failure_cases.md",
    }
    assert json.loads((tmp_path / "case_results.json").read_text())[0]["case_id"] == "STAY-027"
    assert "Operational Decision Accuracy" in render_summary_markdown(summary)
    assert "STAY-027" in render_failure_cases(results)


def test_improved_run_uses_distinct_summary_names(tmp_path: Path) -> None:
    case = run_golden_case(
        _case("STAY-001"),
        settings=DISABLED_TRACING,
        run_version="improved-v1",
    )
    from src.evaluation.golden_contracts import GoldenRunResults

    results = GoldenRunResults(
        dataset_version="v1",
        run_version="improved-v1",
        synthesizer_mode="deterministic",
        dataset_sha256=FROZEN_DATASET_SHA256,
        generated_at=datetime(2026, 9, 3, tzinfo=UTC),
        cases=[case],
    )

    save_results(results, build_summary(results), tmp_path)

    assert (tmp_path / "improved_summary.json").exists()
    assert (tmp_path / "improved_summary.md").exists()
    assert not (tmp_path / "baseline_summary.json").exists()


def test_validation_inventory_and_output_contract() -> None:
    assert VALIDATION_CASES == (
        "STAY-001",
        "STAY-008",
        "STAY-023",
        "STAY-041",
        "STAY-048",
    )
    result = run_golden_case(_case("STAY-041"), settings=DISABLED_TRACING)
    text = format_validation_case(result)

    assert "expected" not in text.casefold()
    assert "intent:" in text
    assert "failure recovery: True" in text
    assert "LangSmith trace ID:" in text
