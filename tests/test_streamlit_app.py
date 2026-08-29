"""Headless Streamlit interaction tests for the Phase 9 dashboard."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.graph import build_phase_8_graph
from src.tools import FailureSimulator, ReadToolName, SimulatedFailureConfig
from src.ui import DashboardController, OPERATING_DATE


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def render_app() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=10).run()


class FailureOnlyDashboardController(DashboardController):
    def load_daily_briefing(self) -> dict:
        result = self.run_query("Are there unresolved guest issues today?")
        self.daily_result = result
        self.daily_thread_id = self.thread_id
        return result


def render_failure_app() -> AppTest:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_GUEST_MESSAGES: 2}
        )
    )
    controller = FailureOnlyDashboardController(
        graph=build_phase_8_graph(
            reference_date=OPERATING_DATE,
            failure_simulator=simulator,
        ),
        thread_id_factory=lambda: "dashboard-source-unavailable",
    )
    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["stayops_controller"] = controller
    return app.run()


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


def test_source_failure_is_prominent_and_requires_acknowledgement() -> None:
    app = render_failure_app()

    assert app.exception == []
    assert any("Analysis incomplete" in item.value for item in app.error)
    assert any("findings are partial" in item.value.lower() for item in app.error)
    assert "Acknowledge" in {button.label for button in app.button}
    assert [(metric.label, metric.value) for metric in app.metric[:3]] == [
        ("Need attention", "0"),
        ("Watch", "8"),
        ("Ready", "0"),
    ]

    app = next(
        button for button in app.button if button.label == "Acknowledge"
    ).click().run()

    controller = app.session_state["stayops_controller"]
    assert controller.result["executed_actions"] == []
    assert any("No simulated action was executed" in item.value for item in app.success)
