"""Controlled Phase 10 evaluation scenarios and reporting."""

from importlib import import_module
from typing import Any

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
__all__ = [
    "AggregateMetric",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SCENARIO_PATH",
    "EvaluationMetric",
    "EvaluationReport",
    "EvaluationScenario",
    "FailureExpectation",
    "MetricObservation",
    "ScenarioCategory",
    "ScenarioResult",
    "ScenarioResults",
    "WriteExpectation",
    "load_scenarios",
    "run_evaluations",
    "save_evaluation_results",
]


def __getattr__(name: str) -> Any:
    """Load runner exports lazily so ``python -m`` does not preload its module."""

    if name in {
        "DEFAULT_OUTPUT_DIR",
        "DEFAULT_SCENARIO_PATH",
        "load_scenarios",
        "run_evaluations",
        "save_evaluation_results",
    }:
        return getattr(import_module("src.evaluation.runner"), name)
    raise AttributeError(name)
