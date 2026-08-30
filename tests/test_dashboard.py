"""Pure presenter and graph-controller tests for the Phase 9 dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import mkdtemp

import pytest

from src.models import WriteToolName
from src.tools import SimulatedOperationsStore
from src.ui import (
    ActivityStatus,
    DashboardController,
    PropertyHealth,
    build_property_summaries,
    count_property_health,
    evidence_for_action,
    incomplete_analysis_message,
)


REFERENCE_DATE = date(2026, 8, 28)


def deterministic_controller() -> DashboardController:
    thread_ids = iter(["dashboard-daily", "dashboard-query"])
    return DashboardController(
        reference_date=REFERENCE_DATE,
        thread_id_factory=lambda: next(thread_ids),
        runtime_store=SimulatedOperationsStore(
            Path(mkdtemp(prefix="stayops-dashboard-test-"))
        ),
    )


def test_daily_dashboard_summarizes_all_eight_properties() -> None:
    controller = deterministic_controller()

    result = controller.load_daily_briefing()
    summaries = build_property_summaries(result)
    counts = count_property_health(summaries)

    assert len(summaries) == 8
    assert controller.has_user_query is False
    assert counts == {
        PropertyHealth.NEEDS_ATTENTION: 2,
        PropertyHealth.WATCH: 3,
        PropertyHealth.READY: 3,
    }
    assert sum(counts.values()) == 8
    assert {summary.name for summary in summaries} == {
        "Lake House",
        "Pine House",
        "City Loft",
        "Garden Cottage",
        "Sunset House",
        "Beach Bungalow",
        "Mountain Retreat",
        "Downtown Suite",
    }


def test_default_controller_uses_current_operating_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_date = date(2026, 8, 29)
    monkeypatch.setattr(
        "src.agents.request_router.current_operating_date",
        lambda: expected_date,
    )
    monkeypatch.setattr(
        "src.ui.dashboard.current_operating_date",
        lambda: expected_date,
    )
    controller = DashboardController(
        thread_id_factory=lambda: "dynamic-date-test",
        runtime_store=SimulatedOperationsStore(
            Path(mkdtemp(prefix="stayops-dynamic-date-test-"))
        ),
    )

    result = controller.load_daily_briefing()

    assert result["date_scope"] == expected_date.isoformat()


def test_dynamic_daily_briefing_detects_calendar_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = [date(2026, 8, 29)]
    monkeypatch.setattr(
        "src.agents.request_router.current_operating_date",
        lambda: current_date[0],
    )
    monkeypatch.setattr(
        "src.ui.dashboard.current_operating_date",
        lambda: current_date[0],
    )
    controller = DashboardController(
        thread_id_factory=lambda: "rollover-test",
        runtime_store=SimulatedOperationsStore(
            Path(mkdtemp(prefix="stayops-rollover-test-"))
        ),
    )
    controller.load_daily_briefing()

    assert controller.daily_briefing_needs_refresh is False

    current_date[0] = date(2026, 8, 30)

    assert controller.daily_briefing_needs_refresh is True


def test_property_summary_uses_highest_priority_attention_finding() -> None:
    controller = deterministic_controller()
    result = controller.load_daily_briefing()

    summaries = {
        summary.property_id: summary for summary in build_property_summaries(result)
    }

    assert summaries["prop_lake_house"].health == PropertyHealth.NEEDS_ATTENTION
    assert "cleaner confirmation" in summaries["prop_lake_house"].headline.lower()
    assert summaries["prop_pine_house"].health == PropertyHealth.NEEDS_ATTENTION
    assert summaries["prop_garden_cottage"].health == PropertyHealth.READY


def test_review_action_maps_only_to_its_supporting_evidence() -> None:
    controller = deterministic_controller()
    controller.load_daily_briefing()
    request = controller.pending_review
    assert request is not None
    action = next(
        action
        for action in request["proposed_actions"]
        if action["tool_name"] == WriteToolName.SEND_CLEANER_MESSAGE
    )

    evidence = evidence_for_action(action, request["findings"])

    record_ids = {
        record_id for item in evidence for record_id in item["record_ids"]
    }
    assert "clean_lake_001" in record_ids
    assert "maint_pine_001" not in record_ids


def test_ask_stayops_uses_new_thread_without_replacing_daily_portfolio() -> None:
    controller = deterministic_controller()
    controller.load_daily_briefing()

    query_result = controller.run_query(
        "Which guests are arriving at City Loft today?"
    )

    assert controller.thread_id == "dashboard-query"
    assert controller.has_user_query is True
    assert controller.pending_review is None
    assert query_result["property_scope"] == ["prop_city_loft"]
    assert controller.daily_result is not None
    assert len(build_property_summaries(controller.daily_result)) == 8


def test_dashboard_date_refresh_preserves_latest_query_and_answer_scope() -> None:
    thread_ids = iter(["daily-aug-28", "query-aug-29", "daily-aug-30"])
    controller = DashboardController(
        reference_date=REFERENCE_DATE,
        thread_id_factory=lambda: next(thread_ids),
        runtime_store=SimulatedOperationsStore(
            Path(mkdtemp(prefix="stayops-date-separation-test-"))
        ),
    )
    controller.load_daily_briefing(REFERENCE_DATE)
    query = "Who is checking in tomorrow?"
    query_result = controller.run_query(query)

    controller.load_daily_briefing(date(2026, 8, 30))

    assert controller.daily_result is not None
    assert controller.daily_result["date_scope"] == "2026-08-30"
    assert controller.result is query_result
    assert controller.result["date_scope"] == "2026-08-29"
    assert controller.last_query == query
    assert controller.thread_id == "query-aug-29"
    assert controller.has_user_query is True


def test_user_query_stream_reports_live_activity_and_final_state() -> None:
    controller = deterministic_controller()
    activity_snapshots: list[dict[str, ActivityStatus]] = []

    result = controller.run_query(
        "Which guests are arriving at City Loft today?",
        on_activity=lambda: activity_snapshots.append(
            {
                key: step.status
                for key, step in controller.activity_steps.items()
            }
        ),
    )

    assert len(activity_snapshots) > 3
    assert activity_snapshots[0]["request_router"] == ActivityStatus.RUNNING
    assert any(
        snapshot["booking_agent"] == ActivityStatus.RUNNING
        for snapshot in activity_snapshots
    )
    assert controller.activity_steps["response_generator"].status == (
        ActivityStatus.COMPLETED
    )
    assert controller.activity_steps["guest_agent"].status == (
        ActivityStatus.NOT_NEEDED
    )
    assert controller.activity_running is False
    assert result["response_generated"] is True


def test_controller_resumes_approval_on_same_thread_and_exposes_execution() -> None:
    controller = deterministic_controller()
    controller.load_daily_briefing()
    request = controller.pending_review
    assert request is not None
    action = next(
        action
        for action in request["proposed_actions"]
        if action["tool_name"] == WriteToolName.SEND_CLEANER_MESSAGE
    )

    completed = controller.resume_review(
        "approve",
        action_id=action["action_id"],
    )

    assert controller.thread_id == "dashboard-daily"
    assert controller.pending_review is not None
    assert len(controller.pending_review["proposed_actions"]) == (
        len(request["proposed_actions"]) - 1
    )
    assert completed["human_decision"]["decision"] == "approve"
    assert completed["executed_actions"][0]["tool_name"] == (
        WriteToolName.SEND_CLEANER_MESSAGE
    )
    assert controller.daily_result == completed


def test_incomplete_analysis_message_names_sources_and_rejects_false_all_clear() -> None:
    assert incomplete_analysis_message(
        {
            "analysis_complete": False,
            "unavailable_sources": ["get_guest_messages"],
        }
    ) == (
        "Analysis incomplete: guest messages remained unavailable after retry. "
        "Findings are partial; absence of findings is not an all-clear."
    )
    assert incomplete_analysis_message(
        {"analysis_complete": True, "unavailable_sources": []}
    ) is None


def test_incomplete_analysis_message_identifies_synthesis_failure() -> None:
    assert incomplete_analysis_message(
        {
            "analysis_complete": False,
            "synthesis_complete": False,
            "unavailable_sources": [],
        }
    ) == (
        "Analysis incomplete: operations synthesis could not be completed. "
        "Findings are incomplete; absence of findings is not an all-clear."
    )


def test_incomplete_analysis_does_not_mark_unverified_properties_ready() -> None:
    result = {
        "analysis_complete": False,
        "property_context": {
            "prop_test_house": {
                "name": "Test House",
                "location": "Testville",
            }
        },
        "operational_findings": [],
    }

    summary = build_property_summaries(result)[0]

    assert summary.health == PropertyHealth.WATCH
    assert summary.headline == "Analysis incomplete; verify unavailable source data."
