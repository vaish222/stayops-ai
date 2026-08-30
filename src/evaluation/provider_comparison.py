"""Repeat the controlled StayOps evaluation across synthesis providers."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from src.evaluation.contracts import EvaluationReport, ScenarioResults
from src.evaluation.runner import (
    DEFAULT_SCENARIO_PATH,
    load_scenarios,
    run_evaluations,
    save_evaluation_results,
)
from src.llm import SynthesizerMode, SynthesizerSettings
from src.llm.factory import build_synthesis_runner


DEFAULT_COMPARISON_DIR = Path("evaluation/results/provider_comparison")
DEFAULT_NEBIUS_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
DEFAULT_OLLAMA_MODEL = "mistral:latest"
PROVIDERS = ("deterministic", "ollama", "nebius")


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "average": round(mean(values), 3) if values else 0.0,
        "median": round(median(values), 3) if values else 0.0,
        "p95": _percentile(values, 0.95),
        "maximum": round(max(values), 3) if values else 0.0,
    }


def _provider_settings(
    provider: str,
    environment: Mapping[str, str],
    *,
    nebius_model: str,
    ollama_model: str,
) -> SynthesizerSettings:
    if provider == "deterministic":
        return SynthesizerSettings(mode=SynthesizerMode.DETERMINISTIC)
    overrides = {
        "SYNTHESIZER_MODE": "llm",
        "LLM_PROVIDER": provider,
        "LLM_MODEL": nebius_model if provider == "nebius" else ollama_model,
        "LLM_SYNTHESIZER_FALLBACK": "deterministic",
    }
    return SynthesizerSettings.from_environment({**environment, **overrides})


def summarize_provider(
    provider: str,
    results_by_run: Sequence[ScenarioResults],
    reports_by_run: Sequence[EvaluationReport],
) -> dict[str, Any]:
    """Aggregate repeated scenario results without averaging away failures."""

    scenarios = [
        scenario
        for results in results_by_run
        for scenario in results.scenarios
    ]
    synthesis_runs = [
        synthesis
        for scenario in scenarios
        if (synthesis := scenario.observations.get("synthesis_run")) is not None
    ]
    completed = sum(run.get("status") == "completed" for run in synthesis_runs)
    fallback = sum(bool(run.get("fallback_used")) for run in synthesis_runs)
    failed = sum(run.get("status") == "failed" for run in synthesis_runs)
    error_codes = Counter(
        str(run["error_code"])
        for run in synthesis_runs
        if run.get("error_code")
    )

    metric_totals: Counter[str] = Counter()
    metric_passes: Counter[str] = Counter()
    for scenario in scenarios:
        for metric in scenario.metrics:
            if not metric.applicable:
                continue
            name = metric.metric.value
            metric_totals[name] += 1
            metric_passes[name] += int(metric.passed is True)

    scenario_totals = Counter(scenario.scenario_id for scenario in scenarios)
    scenario_passes = Counter(
        scenario.scenario_id for scenario in scenarios if scenario.passed
    )
    synthesis_latencies = [
        float(run.get("latency_ms", 0)) for run in synthesis_runs
    ]
    scenario_latencies = [scenario.latency_ms for scenario in scenarios]
    synthesis_count = len(synthesis_runs)
    return {
        "provider": provider,
        "models": sorted(
            {
                str(run["model"])
                for run in synthesis_runs
                if run.get("model")
            }
        ),
        "evaluation_runs": len(results_by_run),
        "all_targets_met_runs": sum(
            report.all_targets_met for report in reports_by_run
        ),
        "scenario_runs": len(scenarios),
        "passed_scenario_runs": sum(scenario.passed for scenario in scenarios),
        "scenario_pass_rate": (
            round(sum(scenario.passed for scenario in scenarios) / len(scenarios), 4)
            if scenarios
            else 0.0
        ),
        "scenario_pass_rates": {
            scenario_id: round(
                scenario_passes[scenario_id] / total,
                4,
            )
            for scenario_id, total in sorted(scenario_totals.items())
        },
        "metric_pass_rates": {
            name: round(metric_passes[name] / total, 4)
            for name, total in sorted(metric_totals.items())
        },
        "end_to_end_latency_ms": _latency_summary(scenario_latencies),
        "synthesis": {
            "run_count": synthesis_count,
            "completed_count": completed,
            "fallback_count": fallback,
            "failed_count": failed,
            "native_completion_rate": (
                round(completed / synthesis_count, 4)
                if synthesis_count
                else 0.0
            ),
            "fallback_rate": (
                round(fallback / synthesis_count, 4)
                if synthesis_count
                else 0.0
            ),
            "grounding_failure_rate": (
                round(
                    error_codes["llm_grounding_failure"] / synthesis_count,
                    4,
                )
                if synthesis_count
                else 0.0
            ),
            "model_or_schema_failure_rate": (
                round(
                    (
                        error_codes["llm_provider_failure"]
                        + error_codes["llm_schema_validation_failure"]
                    )
                    / synthesis_count,
                    4,
                )
                if synthesis_count
                else 0.0
            ),
            "error_codes": dict(sorted(error_codes.items())),
            "latency_ms": _latency_summary(synthesis_latencies),
        },
    }


def _load_provider_runs(
    provider: str,
    output_dir: Path,
    runs: int,
) -> tuple[list[ScenarioResults], list[EvaluationReport]]:
    results: list[ScenarioResults] = []
    reports: list[EvaluationReport] = []
    for run_number in range(1, runs + 1):
        destination = output_dir / provider / f"run-{run_number}"
        results.append(
            ScenarioResults.model_validate_json(
                (destination / "scenario_results.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        reports.append(
            EvaluationReport.model_validate_json(
                (destination / "aggregate_report.json").read_text(
                    encoding="utf-8"
                )
            )
        )
    return results, reports


def _write_comparison_report(
    *,
    output_dir: Path,
    runs: int,
    scenario_count: int,
) -> dict[str, Any]:
    summaries = []
    for provider in PROVIDERS:
        provider_results, provider_reports = _load_provider_runs(
            provider,
            output_dir,
            runs,
        )
        summaries.append(
            summarize_provider(provider, provider_results, provider_reports)
        )
    comparison = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runs_per_provider": runs,
        "scenario_count_per_run": scenario_count,
        "providers": summaries,
        "interpretation": {
            "fallback_policy": (
                "Fallback results remain safe but count against native model "
                "completion; compare fallback_rate before scenario_pass_rate."
            ),
            "cost_tracking": (
                "Provider token usage and monetary cost are not exposed by the "
                "current synthesis metadata and are not scored."
            ),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison_report.json").write_text(
        json.dumps(comparison, indent=2) + "\n",
        encoding="utf-8",
    )
    return comparison


def run_provider_comparison(
    *,
    runs: int = 5,
    scenario_path: Path = DEFAULT_SCENARIO_PATH,
    output_dir: Path = DEFAULT_COMPARISON_DIR,
    environment: Mapping[str, str] | None = None,
    nebius_model: str = DEFAULT_NEBIUS_MODEL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    providers: Sequence[str] = PROVIDERS,
) -> dict[str, Any]:
    """Run identical scenarios for all providers and persist one comparison."""

    if runs < 1:
        raise ValueError("runs must be at least 1")
    invalid_providers = set(providers).difference(PROVIDERS)
    if invalid_providers:
        raise ValueError(
            f"unsupported comparison providers: {sorted(invalid_providers)}"
        )
    env = os.environ if environment is None else environment
    scenarios = load_scenarios(scenario_path)
    for provider in providers:
        settings = _provider_settings(
            provider,
            env,
            nebius_model=nebius_model,
            ollama_model=ollama_model,
        )
        synthesis_runner = build_synthesis_runner(settings)
        for run_number in range(1, runs + 1):
            print(f"[{provider}] run {run_number}/{runs}", flush=True)
            results, report = run_evaluations(
                scenarios,
                synthesis_runner=synthesis_runner,
            )
            destination = output_dir / provider / f"run-{run_number}"
            save_evaluation_results(results, report, destination)
    return _write_comparison_report(
        output_dir=output_dir,
        runs=runs,
        scenario_count=len(scenarios),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare StayOps deterministic, Ollama, and Nebius synthesis"
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_COMPARISON_DIR)
    parser.add_argument("--nebius-model", default=DEFAULT_NEBIUS_MODEL)
    parser.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=PROVIDERS,
        default=list(PROVIDERS),
    )
    args = parser.parse_args()
    comparison = run_provider_comparison(
        runs=args.runs,
        scenario_path=args.scenarios,
        output_dir=args.output_dir,
        nebius_model=args.nebius_model,
        ollama_model=args.ollama_model,
        providers=args.providers,
    )
    for provider in comparison["providers"]:
        synthesis = provider["synthesis"]
        print(
            f"{provider['provider']}: "
            f"scenario pass {provider['scenario_pass_rate']:.1%}; "
            f"native completion {synthesis['native_completion_rate']:.1%}; "
            f"p95 synthesis {synthesis['latency_ms']['p95']:.1f}ms",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
