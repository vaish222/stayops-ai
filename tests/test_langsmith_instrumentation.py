"""Week 4 LangSmith instrumentation tests with no external trace writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.evaluation.langsmith_runner import (
    build_trace_config,
    format_summary,
    load_langsmith_case,
    run_langsmith_case,
    save_langsmith_result,
)
from src.observability import (
    LangSmithSettings,
    collect_read_tool_calls,
    trace_read_tool_call,
)


ROOT_RUN_ID = UUID("11111111-2222-3333-4444-555555555555")
GENERATED_AT = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


def test_langsmith_settings_are_disabled_by_default() -> None:
    settings = LangSmithSettings.from_environment({})

    assert settings.enabled is False
    assert settings.api_key is None
    assert settings.project == "stayops-week4-eval"


def test_enabled_langsmith_settings_require_api_key() -> None:
    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY"):
        LangSmithSettings.from_environment({"LANGSMITH_TRACING": "true"})


def test_langsmith_settings_load_supported_environment() -> None:
    settings = LangSmithSettings.from_environment(
        {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "secret",
            "LANGSMITH_PROJECT": "stayops-test",
            "LANGSMITH_WORKSPACE_ID": "workspace",
            "LANGSMITH_ENDPOINT": "https://example.test",
        }
    )

    assert settings.enabled is True
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "secret"
    assert settings.project == "stayops-test"
    assert settings.workspace_id == "workspace"
    assert settings.endpoint == "https://example.test"


def test_stay_001_preserves_the_exact_baseline_case() -> None:
    case = load_langsmith_case()

    assert case.case_id == "STAY-001"
    assert case.query == "Who is checking in tomorrow?"
    assert case.reference_date.isoformat() == "2026-09-02"
    assert case.expected.intent == "arrivals"
    assert case.expected.resolved_date_scope == "2026-09-03"
    assert case.expected.specialists == ["booking"]
    assert case.expected.human_review is False


def test_trace_config_has_one_named_root_and_expected_metadata_only() -> None:
    case = load_langsmith_case()
    config = build_trace_config(case, ROOT_RUN_ID)

    assert config["run_name"] == "StayOps Evaluation Run"
    assert config["run_id"] == ROOT_RUN_ID
    assert config["metadata"]["case_id"] == "STAY-001"
    assert config["metadata"]["expected_intent"] == "arrivals"
    assert config["metadata"]["expected_specialists"] == ["booking"]
    assert all(
        not key.startswith("actual_") for key in config["metadata"]
    )


def test_read_tool_trace_preserves_result_and_records_actual_attempt() -> None:
    expected = object()

    with collect_read_tool_calls() as calls:
        observed = trace_read_tool_call(
            "get_reservations",
            1,
            lambda: expected,
        )

    assert observed is expected
    assert calls == [{"tool_name": "get_reservations", "attempt": 1}]


def test_stay_001_records_current_mismatches_without_network_calls() -> None:
    case = load_langsmith_case()
    result = run_langsmith_case(
        case,
        settings=LangSmithSettings(enabled=False),
        run_id=ROOT_RUN_ID,
        generated_at=GENERATED_AT,
    )

    assert result.tracing_enabled is False
    assert result.run_id == ROOT_RUN_ID
    assert result.trace_id == ROOT_RUN_ID
    assert result.actual.predicted_intent == "general_operations"
    assert result.actual.resolved_date_scope == "2026-09-03"
    assert result.actual.resolved_property_ids == []
    assert result.actual.activated_specialists == [
        "booking",
        "guest",
        "turnover",
        "maintenance",
    ]
    assert result.actual.tools_called == [
        "get_properties",
        "get_property_rules",
        "get_reservations",
        "get_guest_messages",
        "get_cleaning_schedule",
        "get_maintenance_tickets",
    ]
    assert result.actual.human_review_triggered is True
    assert result.actual.outcome == "interrupted"
    assert result.actual.response_generated is False
    assert result.actual.workflow_errors == []
    assert result.comparisons == {
        "intent": False,
        "date_scope": True,
        "property_scope": True,
        "specialists": False,
        "human_review": False,
    }
    assert result.all_expectations_met is False


def test_baseline_summary_treats_mismatches_as_observations() -> None:
    result = run_langsmith_case(
        load_langsmith_case(),
        settings=LangSmithSettings(enabled=False),
        run_id=ROOT_RUN_ID,
        generated_at=GENERATED_AT,
    )

    summary = format_summary(result)

    assert "STAY-001 · untouched baseline" in summary
    assert "FAIL Intent" in summary
    assert "PASS Date scope" in summary
    assert "Workflow outcome: interrupted" in summary
    assert "Baseline expectations met: false" in summary


def test_local_result_preserves_run_and_trace_identifiers(tmp_path) -> None:
    result = run_langsmith_case(
        load_langsmith_case(),
        settings=LangSmithSettings(enabled=False),
        run_id=ROOT_RUN_ID,
        generated_at=GENERATED_AT,
    )
    destination = tmp_path / "stay_001.json"

    save_langsmith_result(result, destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["run_id"] == str(ROOT_RUN_ID)
    assert payload["trace_id"] == str(ROOT_RUN_ID)
    assert payload["expected"]["intent"] == "arrivals"
    assert payload["actual"]["predicted_intent"] == "general_operations"
