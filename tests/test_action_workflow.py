"""Phase 8 checkpoint-to-approved-simulation workflow tests."""

from __future__ import annotations

from datetime import date

import pytest
from langgraph.types import Command

from src.graph import build_phase_8_graph, create_initial_state
from src.models import WriteToolName


REFERENCE_DATE = date(2026, 8, 28)


def start_review(graph, *, query: str, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    paused = graph.invoke(
        create_initial_state(query, request_id=thread_id),
        config=config,
    )
    return config, paused, paused["__interrupt__"][0].value


@pytest.mark.parametrize(
    ("query", "tool_name", "target_record_id"),
    [
        (
            "What needs my attention today?",
            WriteToolName.SEND_CLEANER_MESSAGE,
            "clean_lake_001",
        ),
        (
            "What guest issues need attention at Pine House today?",
            WriteToolName.SEND_GUEST_MESSAGE,
            "msg_pine_001",
        ),
        (
            "What maintenance needs attention at Pine House today?",
            WriteToolName.UPDATE_MAINTENANCE_STATUS,
            "maint_pine_001",
        ),
    ],
)
def test_approved_action_executes_only_its_matching_simulated_tool(
    query: str,
    tool_name: WriteToolName,
    target_record_id: str,
) -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    thread_id = f"phase-8-{tool_name.value}"
    config, paused, request = start_review(
        graph,
        query=query,
        thread_id=thread_id,
    )
    action = next(
        action
        for action in request["proposed_actions"]
        if action["tool_name"] == tool_name
    )

    completed = graph.invoke(
        Command(
            resume={"decision": "approve", "action_id": action["action_id"]}
        ),
        config=config,
    )

    assert paused["action_attempts"] == []
    assert paused["executed_actions"] == []
    assert len(completed["approval_grants"]) == 1
    assert completed["approval_grants"][0]["request_id"] == thread_id
    assert completed["approval_grants"][0]["action_id"] == action["action_id"]
    assert len(completed["action_attempts"]) == 1
    assert completed["action_attempts"][0]["status"] == "executed"
    assert completed["action_attempts"][0]["approved"] is True
    assert len(completed["executed_actions"]) == 1
    assert completed["executed_actions"][0]["tool_name"] == tool_name
    assert completed["executed_actions"][0]["target_record_id"] == target_record_id
    assert completed["executed_actions"][0]["simulated"] is True


def test_rejected_action_produces_no_token_attempt_or_execution() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(
        graph,
        query="What needs my attention today?",
        thread_id="phase-8-reject",
    )
    action_id = request["proposed_actions"][0]["action_id"]

    completed = graph.invoke(
        Command(resume={"decision": "reject", "action_id": action_id}),
        config=config,
    )

    assert completed["human_decision"]["decision"] == "reject"
    assert completed["approval_grants"] == []
    assert completed["action_attempts"] == []
    assert completed["executed_actions"] == []


def test_approving_non_executable_review_records_no_write_attempt() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(
        graph,
        query="What needs my attention today?",
        thread_id="phase-8-review-only",
    )
    review_action = next(
        action for action in request["proposed_actions"] if action["tool_name"] is None
    )

    completed = graph.invoke(
        Command(
            resume={
                "decision": "approve",
                "action_id": review_action["action_id"],
            }
        ),
        config=config,
    )

    assert completed["human_decision"]["decision"] == "approve"
    assert completed["approval_grants"] == []
    assert completed["action_attempts"] == []
    assert completed["executed_actions"] == []


def test_edited_message_requires_reconfirmation_and_executes_exact_edit() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(
        graph,
        query="What needs my attention today?",
        thread_id="phase-8-edit",
    )
    action = next(
        action
        for action in request["proposed_actions"]
        if action["tool_name"] == WriteToolName.SEND_CLEANER_MESSAGE
    )
    edited_message = "Please confirm the Lake House turnover by 1 PM."

    reconfirmation = graph.invoke(
        Command(
            resume={
                "decision": "edit",
                "action_id": action["action_id"],
                "edited_description": edited_message,
            }
        ),
        config=config,
    )
    edited_action = next(
        proposed
        for proposed in reconfirmation["__interrupt__"][0].value[
            "proposed_actions"
        ]
        if proposed["action_id"] == action["action_id"]
    )

    assert edited_action["description"] == edited_message
    assert edited_action["parameters"] == {"message": edited_message}
    assert reconfirmation["approval_grants"] == []
    assert reconfirmation["action_attempts"] == []

    completed = graph.invoke(
        Command(
            resume={"decision": "approve", "action_id": action["action_id"]}
        ),
        config=config,
    )

    assert completed["executed_actions"][0]["result"]["message"] == edited_message
    assert completed["executed_actions"][0]["action_id"] == action["action_id"]


def test_safe_read_path_never_reaches_write_execution() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    config = {"configurable": {"thread_id": "phase-8-safe-read"}}

    completed = graph.invoke(
        create_initial_state(
            "Which guests are arriving at City Loft today?",
            request_id="phase-8-safe-read",
        ),
        config=config,
    )

    assert "__interrupt__" not in completed
    assert completed["requires_human_review"] is False
    assert completed["approval_grants"] == []
    assert completed["action_attempts"] == []
    assert completed["executed_actions"] == []


def test_phase_8_adds_execution_without_ui_or_external_write_nodes() -> None:
    graph = build_phase_8_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert "human_review" in node_names
    assert "execute_approved_actions" in node_names
    assert not {"streamlit_ui", "dashboard", "external_api_write"} & node_names
