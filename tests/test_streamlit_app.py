"""Headless Streamlit interaction tests for the StayOps command center."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from tempfile import mkdtemp

import pytest
from streamlit.testing.v1 import AppTest

from app import _group_approval_actions
from src.graph import build_phase_8_graph
from src.tools import (
    FailureSimulator,
    ReadToolName,
    SimulatedFailureConfig,
    SimulatedOperationsStore,
)
from src.ui import DashboardController


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
REFERENCE_DATE = date(2026, 8, 28)


def render_app(view: str | None = None) -> AppTest:
    runtime_store = SimulatedOperationsStore(
        Path(mkdtemp(prefix="stayops-ui-test-")),
        clock=lambda: datetime.combine(
            REFERENCE_DATE,
            time(hour=23, minute=59),
            tzinfo=timezone.utc,
        ),
    )
    controller = DashboardController(
        reference_date=REFERENCE_DATE,
        runtime_store=runtime_store,
    )
    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["stayops_controller"] = controller
    if view is not None:
        app.query_params["view"] = view
    return app.run()


class FailureOnlyDashboardController(DashboardController):
    def load_daily_briefing(self) -> dict:
        result = self.run_query(
            "Are there unresolved guest issues today?",
            user_initiated=False,
        )
        self.daily_result = result
        self.daily_thread_id = self.thread_id
        return result


def render_failure_app() -> AppTest:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_GUEST_MESSAGES: 2}
        )
    )
    runtime_store = SimulatedOperationsStore(
        Path(mkdtemp(prefix="stayops-ui-failure-test-"))
    )
    controller = FailureOnlyDashboardController(
        graph=build_phase_8_graph(
            reference_date=REFERENCE_DATE,
            failure_simulator=simulator,
            runtime_store=runtime_store,
        ),
        thread_id_factory=lambda: "dashboard-source-unavailable",
        runtime_store=runtime_store,
        reference_date=REFERENCE_DATE,
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
    assert "✨ StayOps Answer" not in page_markup
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
        "Reject",
        "What's urgent today?",
        "Who's checking in?",
        "Cleaning risks",
        "Guests needing replies",
    }
    assert page_markup.count("Your approval is needed") == 1
    assert "StayOps found actions it cannot take without you." in page_markup
    assert "Nothing is sent or changed until you approve." in page_markup
    assert "Why now" in page_markup
    assert "Approval required" in page_markup
    assert "Contact cleaner" in page_markup
    assert "Same-day turnover has a missing cleaner confirmation." in page_markup
    assert (
        "Approval is required because this action sends a message to the cleaner."
        in page_markup
    )
    assert "Proposed message" in page_markup
    assert (
        "Please confirm whether the scheduled turnover will be completed by the target time."
        in page_markup
    )
    assert "Update maintenance status" in page_markup
    assert "Proposed change" in page_markup
    assert "Maintenance status" in page_markup
    assert "Open" in page_markup
    assert "In Progress" in page_markup
    controller = app.session_state["stayops_controller"]
    expected_property_groups = len(
        _group_approval_actions(controller.pending_review["proposed_actions"])
    )
    approval_headers = [
        item.value
        for item in app.markdown
        if item.value.startswith('<div class="approval-property-header">')
    ]
    assert len(approval_headers) == expected_property_groups
    assert any("2 actions need your approval" in header for header in approval_headers)
    assert {expander.label for expander in app.expander} >= {"View source details"}
    assert "Why StayOps suggested this" not in {
        expander.label for expander in app.expander
    }
    assert sum("Simulation mode:" in item.value for item in app.caption) == 1
    assert "Edit" not in {button.label for button in app.button}
    assert len(app.text_area) == 0


def test_approval_actions_are_grouped_by_property_in_priority_order() -> None:
    actions = [
        {"action_id": "first", "property_id": "prop_lake_house"},
        {"action_id": "second", "property_id": "prop_pine_house"},
        {"action_id": "third", "property_id": "prop_lake_house"},
    ]

    grouped = _group_approval_actions(actions)

    assert [property_id for property_id, _ in grouped] == [
        "prop_lake_house",
        "prop_pine_house",
    ]
    assert [action["action_id"] for action in grouped[0][1]] == ["first", "third"]


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
    visible_property_copy = "\n".join(
        item.value for item in [*app.markdown, *app.text]
    )
    assert "Assigned cleaner: Alex Meadow" in visible_property_copy
    assert "Confirmation pending" in visible_property_copy
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


@pytest.mark.parametrize(
    ("view", "tab_label"),
    [
        ("guest_messages", "Guest Messages"),
        ("turnovers", "Turnovers"),
        ("maintenance", "Maintenance"),
    ],
)
def test_sidebar_operations_links_open_the_requested_tab(
    view: str,
    tab_label: str,
) -> None:
    app = render_app(view)

    assert app.exception == []
    assert len(app.tabs) == 5
    assert tab_label in [tab.label for tab in app.tabs]
    assert app.session_state["operations_tab"] == tab_label
    assert app.radio(key="sidebar_navigation").value == tab_label
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Operations Workspace" in page_markup
    assert "Portfolio Overview" not in page_markup


def test_sidebar_navigation_click_updates_url_and_active_page() -> None:
    app = render_app()
    navigation = app.radio(key="sidebar_navigation")
    assert navigation.options == [
        "Command Center",
        "Properties",
        "Guest Messages",
        "Turnovers",
        "Maintenance",
        "Approvals",
    ]

    app = navigation.set_value("Turnovers").run()

    assert app.exception == []
    assert app.query_params["view"] in ("turnovers", ["turnovers"])
    assert app.radio(key="sidebar_navigation").value == "Turnovers"
    assert len(app.tabs) == 5
    assert app.session_state["operations_tab"] == "Turnovers"
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Operations Workspace" in page_markup
    assert "Portfolio Overview" not in page_markup


def test_home_button_returns_to_command_center_in_one_click() -> None:
    app = render_app("maintenance")
    app = app.selectbox(key="property_drilldown").select("Lake House").run()

    app = app.button(key="home_button").click().run()

    assert app.exception == []
    assert app.query_params["view"] in ("command_center", ["command_center"])
    assert app.radio(key="sidebar_navigation").value == "Command Center"
    assert app.selectbox(key="property_drilldown").value == "All properties"
    assert len(app.tabs) == 5
    assert app.session_state["operations_tab"] == "Needs Your Attention"
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Ask StayOps" in page_markup
    assert "Portfolio Overview" in page_markup


def test_sidebar_switches_between_turnovers_and_maintenance_in_one_session() -> None:
    app = render_app()

    app = app.radio(key="sidebar_navigation").set_value("Turnovers").run()
    assert len(app.tabs) == 5
    assert app.session_state["operations_tab"] == "Turnovers"

    app = app.radio(key="sidebar_navigation").set_value("Maintenance").run()

    assert app.exception == []
    assert app.query_params["view"] in ("maintenance", ["maintenance"])
    assert app.radio(key="sidebar_navigation").value == "Maintenance"
    assert app.session_state["operations_tab"] == "Maintenance"
    assert len(app.tabs) == 5


@pytest.mark.parametrize(
    ("view", "label", "heading"),
    [
        ("command_center", "Command Center", "Portfolio Overview"),
        ("properties", "Properties", "Portfolio Overview"),
        ("approvals", "Approvals", "Human Approvals"),
    ],
)
def test_sidebar_non_operations_destinations_render_their_page(
    view: str,
    label: str,
    heading: str,
) -> None:
    app = render_app(view)

    assert app.exception == []
    assert app.radio(key="sidebar_navigation").value == label
    assert heading in "\n".join(item.value for item in app.markdown)


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
    assert controller.has_user_query is True
    assert controller.pending_review is None
    assert not {"Approve & Send", "Approve & Update", "Reject"}.intersection(
        button.label for button in app.button
    )
    assert all("StayOps checked your operations" not in item.value for item in app.info)
    assert any(
        "No approvals are pending" in item.value for item in app.info
    )
    page_markup = "\n".join(item.value for item in app.markdown)
    assert 'id="approval-center"' in page_markup
    assert "1 arrival is scheduled on Aug 28." in page_markup
    assert "Taylor Moon, 3:00 PM, 2 guests" in page_markup
    assert all("existing operations graph" not in item.value for item in app.info)


def test_agent_activity_rail_is_ready_before_a_user_request() -> None:
    app = render_app()

    assert app.exception == []
    assert any("Agent Activity" in item.value for item in app.markdown)
    assert any("Ready for your question" in item.value for item in app.markdown)
    assert app.toggle == []
    assert "Developer details" not in {expander.label for expander in app.expander}


def test_agent_activity_rail_exposes_completed_execution_steps() -> None:
    app = render_app()
    app.text_input[0].input("What needs my attention today?")
    app = next(
        button for button in app.button if button.label == "Ask StayOps"
    ).click().run()

    assert app.exception == []
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Request Router" in page_markup
    assert "Operations Synthesizer" in page_markup
    assert "Safety Gate" in page_markup
    assert "Completed" in page_markup
    assert "Waiting for your approval" in page_markup
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
    assert cleanings[0]["Assigned cleaner"] == "Alex Meadow"
    assert cleanings[0]["Confirmation"] == "Confirmation pending"
    assert cleanings[0]["Target complete"] == "2:00 PM"
    assert maintenance[1]["Status"] == "In Progress"
    assert maintenance[1]["Blocks check-in"] == "No"
    assert arrivals[0]["Source"] == "Marketplace"


def test_approve_executes_the_reviewed_action_without_edit_control() -> None:
    app = render_app()
    controller = app.session_state["stayops_controller"]
    initial_action_count = len(controller.pending_review["proposed_actions"])
    reviewed_message = controller.pending_review["proposed_actions"][0]["description"]
    assert "Edit" not in {button.label for button in app.button}
    assert len(app.text_area) == 0

    app = next(
        button for button in app.button if button.label == "Approve & Send"
    ).click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.pending_review is not None
    assert len(controller.pending_review["proposed_actions"]) == initial_action_count - 1
    assert controller.result["executed_actions"][0]["result"]["message"] == (
        reviewed_message
    )
    assert any("Approved and sent — simulation only" in item.value for item in app.success)
    cleaning = controller.result["cleaning_context"]["clean_lake_001"]
    assert "Simulated reminder sent" in cleaning["notes"]
    assert len(controller.runtime_store.action_history()) == 1
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Simulated action completed" in page_markup
    assert "Waiting for your approval" in page_markup


def test_approve_update_executes_the_visible_status_transition() -> None:
    app = render_app()
    controller = app.session_state["stayops_controller"]
    update_action = next(
        action
        for action in controller.pending_review["proposed_actions"]
        if action.get("tool_name") == "update_maintenance_status"
    )
    target_record_id = update_action["target_record_id"]
    assert controller.result["maintenance_context"][target_record_id]["status"] == "open"

    app = next(
        button for button in app.button if button.label == "Approve & Update"
    ).click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.result["maintenance_context"][target_record_id]["status"] == (
        "in_progress"
    )
    assert any(
        "Approved and updated — simulation only" in item.value
        for item in app.success
    )


def test_reject_control_records_decision_without_execution() -> None:
    app = render_app()

    app = next(button for button in app.button if button.label == "Reject").click().run()

    assert app.exception == []
    controller = app.session_state["stayops_controller"]
    assert controller.result["human_decision"]["decision"] == "reject"
    assert controller.result["executed_actions"] == []
    assert controller.pending_review is not None
    assert any("Action rejected — nothing was sent" in item.value for item in app.info)
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "Action rejected · no write made" in page_markup
    assert "✨ StayOps Answer" not in page_markup


def test_source_failure_is_prominent_and_requires_acknowledgement() -> None:
    app = render_failure_app()

    assert app.exception == []
    assert any("Analysis incomplete" in item.value for item in app.error)
    assert any("findings are partial" in item.value.lower() for item in app.error)
    assert "Acknowledge" in {button.label for button in app.button}
    page_markup = "\n".join(item.value for item in app.markdown)
    assert "✨ StayOps Answer" not in page_markup
    assert '<div class="value">0</div><div class="label">Needs Action</div>' in page_markup
    assert '<div class="value">8</div><div class="label">Watch</div>' in page_markup
    assert '<div class="value">0</div><div class="label">Ready for Guests</div>' in page_markup

    app = next(
        button for button in app.button if button.label == "Acknowledge"
    ).click().run()

    controller = app.session_state["stayops_controller"]
    assert controller.result["executed_actions"] == []
    assert any("No simulated action was executed" in item.value for item in app.success)
