"""Headless Streamlit interaction tests for the Phase 9 dashboard."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def render_app() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=10).run()


def test_dashboard_renders_metrics_portfolio_and_review_controls() -> None:
    app = render_app()

    assert app.exception == []
    assert any("STAYOPS AI" in item.value for item in app.markdown)
    assert [(metric.label, metric.value) for metric in app.metric[:3]] == [
        ("Need attention", "2"),
        ("Watch", "3"),
        ("Ready", "3"),
    ]
    property_selector = app.selectbox(key="property_drilldown")
    assert property_selector.options == [
        "All properties",
        "Beach Bungalow",
        "City Loft",
        "Downtown Suite",
        "Garden Cottage",
        "Lake House",
        "Mountain Retreat",
        "Pine House",
        "Sunset House",
    ]
    assert {button.label for button in app.button} >= {
        "Analyze",
        "Approve",
        "Edit & reconfirm",
        "Reject",
    }


def test_property_selector_opens_operational_drilldown() -> None:
    app = render_app()

    app = app.selectbox(key="property_drilldown").select("Lake House").run()

    assert app.exception == []
    assert "Lake House" in [subheader.value for subheader in app.subheader]
    assert [tab.label for tab in app.tabs] == ["Overview", "Stays", "Operations"]
    assert any(
        "Alex Meadow" in item.value for item in [*app.markdown, *app.text]
    )


def test_ask_stayops_submits_to_graph_and_safe_result_needs_no_review() -> None:
    app = render_app()
    query = "Which guests are arriving at City Loft today?"
    app.text_input[0].input(query)

    app = next(button for button in app.button if button.label == "Analyze").click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.last_query == query
    assert controller.pending_review is None
    assert not {"Approve", "Edit & reconfirm", "Reject"}.intersection(
        button.label for button in app.button
    )
    assert any("existing operations graph" in item.value for item in app.info)


def test_debug_toggle_exposes_specialist_findings() -> None:
    app = render_app()

    app = app.toggle[0].set_value(True).run()

    assert app.exception == []
    assert "Specialist findings · debug" in [
        subheader.value for subheader in app.subheader
    ]
    assert any("Booking" in expander.label for expander in app.expander)
    assert any("Maintenance" in expander.label for expander in app.expander)


def test_edit_reconfirm_and_approve_executes_exact_ui_revision() -> None:
    app = render_app()
    edited_message = "Please confirm Lake House will be ready by 1 PM."
    app.text_area[0].input(edited_message)

    app = next(
        button for button in app.button if button.label == "Edit & reconfirm"
    ).click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.pending_review is not None
    assert app.text_area[0].value == edited_message
    assert any("reconfirmation" in item.value for item in app.warning)

    app = next(button for button in app.button if button.label == "Approve").click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.pending_review is None
    assert controller.result["executed_actions"][0]["result"]["message"] == (
        edited_message
    )
    assert any("1 simulated action executed" in item.value for item in app.success)


def test_reject_control_records_decision_without_execution() -> None:
    app = render_app()

    app = next(button for button in app.button if button.label == "Reject").click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.result["human_decision"]["decision"] == "reject"
    assert controller.result["executed_actions"] == []
    assert any("No action was executed" in item.value for item in app.info)
