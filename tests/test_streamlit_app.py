"""Headless Streamlit interaction tests for the StayOps command center."""

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
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "8 properties. One operations command center." in page_markup
    assert "Know what's ready, what's at risk, and what needs your approval." in page_markup
    assert all(
        label in page_markup
        for label in ("Needs Action", "Watch", "Ready for Guests", "Arrivals Today")
    )
    assert "Needs Your Attention" in page_markup
    assert page_markup.index("Needs Your Attention") < page_markup.index("Ask StayOps")
    attention_cards = [
        item.value for item in app.markdown if 'class="attention-card"' in item.value
    ]
    assert len(attention_cards) == 2
    assert all("needs_attention" in card and "watch" not in card for card in attention_cards)
    assert "2 properties require action · 3 more properties are on watch" in page_markup
    assert "Last StayOps run" in page_markup
    assert page_markup.count("Last StayOps run") == 1
    assert page_markup.index("Ask StayOps") < page_markup.index("Last StayOps run")
    assert "None in scope" not in page_markup
    assert "Prioritized issues" not in page_markup
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
        "Ask StayOps",
        "Approve & Send",
        "Edit",
        "Reject",
        "What's urgent today?",
        "Who's checking in?",
        "Cleaning risks",
        "Guests needing replies",
    }
    assert page_markup.count("Your approval is needed") == 1
    assert "Why your approval is required" in page_markup
    assert any(
        "This action will send a message to the cleaner." in item.value
        for item in app.caption
    )
    assert len(app.text_area) == 6


def test_portfolio_filter_and_view_property_are_interactive() -> None:
    app = render_app()

    app = app.radio(key="portfolio_filter").set_value("Ready for Guests").run()
    assert app.exception == []
    assert len([button for button in app.button if button.label == "View property"]) == 3

    app = next(
        button for button in app.button if button.label == "View property"
    ).click().run()
    assert app.exception == []
    assert app.selectbox(key="property_drilldown").value in {
        "Downtown Suite",
        "Garden Cottage",
        "Sunset House",
    }


def test_property_selector_opens_operational_drilldown() -> None:
    app = render_app()

    app = app.selectbox(key="property_drilldown").select("Lake House").run()

    assert app.exception == []
    assert any("Lake House" in item.value for item in app.markdown)
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Stays",
        "Property Ops",
        "Needs Your Attention",
        "Guest Messages",
        "Turnovers",
        "Maintenance",
        "Arrivals",
    ]
    assert any(
        "Alex Meadow" in item.value for item in [*app.markdown, *app.text]
    )
    assert any("Cleaner-ready buffer 120 minutes" in item.value for item in app.markdown)


def test_dashboard_exposes_dedicated_operations_views() -> None:
    app = render_app()

    assert app.exception == []
    assert [tab.label for tab in app.tabs] == [
        "Needs Your Attention",
        "Guest Messages",
        "Turnovers",
        "Maintenance",
        "Arrivals",
    ]


def test_ask_stayops_submits_to_graph_and_safe_result_needs_no_review() -> None:
    app = render_app()
    query = "Which guests are arriving at City Loft today?"
    app.text_input[0].input(query)

    app = next(
        button for button in app.button if button.label == "Ask StayOps"
    ).click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.last_query == query
    assert controller.pending_review is None
    assert not {"Approve & Send", "Approve & Update", "Edit", "Reject"}.intersection(
        button.label for button in app.button
    )
    assert any("StayOps checked your operations" in item.value for item in app.info)
    assert all("existing operations graph" not in item.value for item in app.info)


def test_agent_activity_toggle_exposes_specialist_findings() -> None:
    app = render_app()

    app = app.toggle[0].set_value(True).run()

    assert app.exception == []
    assert any("Agent Activity" in item.value for item in app.markdown)
    assert any("Request Router" in item.value for item in app.markdown)
    assert any("Operations Synthesizer" in item.value for item in app.markdown)
    assert any("Safety Gate" in item.value for item in app.markdown)
    assert any("Completed" in item.value for item in app.markdown)
    assert any("Human review required" in item.value for item in app.markdown)
    assert "Developer details" in {expander.label for expander in app.expander}
    assert "Structured run details" not in "\n".join(
        item.value for item in app.markdown
    )


def test_agent_activity_marks_unselected_agents_as_not_needed() -> None:
    app = render_app()
    app.text_input[0].input("Which guests are arriving at City Loft today?")
    app = next(
        button for button in app.button if button.label == "Ask StayOps"
    ).click().run()
    app = app.toggle[0].set_value(True).run()

    page_markup = "\n".join(item.value for item in app.markdown)
    assert app.exception == []
    assert "Not needed for this request" in page_markup
    assert "Checks passed" in page_markup


def test_raw_record_ids_are_not_exposed_in_operator_views() -> None:
    app = render_app()

    visible_copy = "\n".join(
        item.value for item in [*app.markdown, *app.text, *app.caption]
    )
    for prefix in ("prop_", "res_", "msg_", "clean_", "maint_"):
        assert prefix not in visible_copy


def test_operations_tables_use_human_readable_values() -> None:
    app = render_app()

    messages = app.dataframe[0].value.to_dict("records")
    cleanings = app.dataframe[1].value.to_dict("records")
    maintenance = app.dataframe[2].value.to_dict("records")
    arrivals = app.dataframe[3].value.to_dict("records")

    assert messages[0]["Received"] == "Aug 28 · 7:10 AM"
    assert messages[0]["Needs response"] == "Yes"
    assert cleanings[0]["Target complete"] == "2:00 PM"
    assert maintenance[1]["Status"] == "In Progress"
    assert maintenance[1]["Blocks check-in"] == "No"
    assert arrivals[0]["Source"] == "Marketplace"


def test_edit_reconfirm_and_approve_executes_exact_ui_revision() -> None:
    app = render_app()
    edited_message = "Please confirm Lake House will be ready by 1 PM."
    app.text_area[0].input(edited_message)

    app = next(button for button in app.button if button.label == "Edit").click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.pending_review is not None
    assert app.text_area[0].value == edited_message
    assert any("reconfirmation" in item.value for item in app.warning)

    app = next(
        button for button in app.button if button.label == "Approve & Send"
    ).click().run()

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
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Action rejected — nothing was sent." in page_markup
    assert page_markup.count("Last StayOps run") == 1


def test_source_failure_is_prominent_and_requires_acknowledgement() -> None:
    app = render_failure_app()

    assert app.exception == []
    assert any("Analysis incomplete" in item.value for item in app.error)
    assert any("findings are partial" in item.value.lower() for item in app.error)
    assert "Acknowledge" in {button.label for button in app.button}
    page_markup = "\n".join(item.value for item in app.markdown)
    assert '<div class="value">0</div><div class="label">Needs Action</div>' in page_markup
    assert '<div class="value">8</div><div class="label">Watch</div>' in page_markup
    assert '<div class="value">0</div><div class="label">Ready for Guests</div>' in page_markup

    app = next(
        button for button in app.button if button.label == "Acknowledge"
    ).click().run()

    controller = app.session_state["stayops_controller"]
    assert controller.result["executed_actions"] == []
    assert any("No simulated action was executed" in item.value for item in app.success)
