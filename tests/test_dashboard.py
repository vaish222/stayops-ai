"""Pure presenter and graph-controller tests for the Phase 9 dashboard."""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

from src.models import WriteToolName
from src.tools import SimulatedOperationsStore
from src.ui import (
    DashboardController,
    PropertyHealth,
    build_property_summaries,
    count_property_health,
    evidence_for_action,
    incomplete_analysis_message,
)


def deterministic_controller() -> DashboardController:
    thread_ids = iter(["dashboard-daily", "dashboard-query"])
    return DashboardController(
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
    assert controller.pending_review is None
    assert query_result["property_scope"] == ["prop_city_loft"]
    assert controller.daily_result is not None
    assert len(build_property_summaries(controller.daily_result)) == 8


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
