"""Phase 7 checkpointed interrupt, decision, and reconfirmation tests."""

from __future__ import annotations

from datetime import date

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from src.graph import build_phase_7_graph, create_initial_state
from src.models import HumanReviewResponse, ReviewDecision


REFERENCE_DATE = date(2026, 8, 28)
REVIEW_QUERY = "Send the cleaner at Lake House a message today."
SAFE_QUERY = "Which guests are arriving at City Loft today?"


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def start_review(graph, *, thread_id: str):
    config = thread_config(thread_id)
    paused = graph.invoke(
        create_initial_state(REVIEW_QUERY, request_id=thread_id),
        config=config,
    )
    return config, paused, paused["__interrupt__"][0].value


def test_review_response_requires_a_complete_edit() -> None:
    with pytest.raises(ValidationError, match="edit requires"):
        HumanReviewResponse(decision=ReviewDecision.EDIT, action_id="action:test")

    with pytest.raises(ValidationError, match="only valid for an edit"):
        HumanReviewResponse(
            decision=ReviewDecision.APPROVE,
            edited_description="Unexpected edit.",
        )


def test_safe_path_completes_without_interrupt() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config = thread_config("phase-7-safe")

    result = graph.invoke(
        create_initial_state(SAFE_QUERY, request_id="phase-7-safe"),
        config=config,
    )

    assert result["requires_human_review"] is False
    assert result["risk_gate_evaluated"] is True
    assert result["human_decision"] is None
    assert "__interrupt__" not in result
    assert result["executed_actions"] == []


def test_review_interrupt_presents_actions_reasons_and_evidence() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)

    _, paused, request = start_review(graph, thread_id="phase-7-payload")

    assert paused["requires_human_review"] is True
    assert paused["human_decision"] is None
    assert request["request_id"] == "phase-7-payload"
    assert request["allowed_decisions"] == ["approve", "edit", "reject"]
    assert request["edit_requires_reconfirmation"] is True
    assert request["proposed_actions"]
    assert request["review_reasons"]
    assert request["findings"]
    assert all(finding["evidence"] for finding in request["findings"])
    assert paused["executed_actions"] == []


def test_approve_resumes_the_same_thread_and_records_scoped_decision() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(graph, thread_id="phase-7-approve")
    action = request["proposed_actions"][0]

    completed = graph.invoke(
        Command(
            resume={
                "decision": "approve",
                "action_id": action["action_id"],
            }
        ),
        config=config,
    )

    assert "__interrupt__" not in completed
    assert completed["human_decision"]["decision"] == "approve"
    assert completed["human_decision"]["review_complete"] is True
    assert completed["human_decision"]["action_ids"] == [action["action_id"]]
    assert completed["human_decision"]["reviewed_actions"] == [action]
    assert completed["executed_actions"] == []


def test_reject_resumes_and_records_rejection_without_action() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(graph, thread_id="phase-7-reject")
    action_id = request["proposed_actions"][0]["action_id"]

    completed = graph.invoke(
        Command(resume={"decision": "reject", "action_id": action_id}),
        config=config,
    )

    assert completed["human_decision"]["decision"] == "reject"
    assert completed["human_decision"]["review_complete"] is True
    assert completed["human_decision"]["action_ids"] == [action_id]
    assert completed["executed_actions"] == []


def test_edit_updates_only_description_and_interrupts_again_for_confirmation() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(graph, thread_id="phase-7-edit")
    original_actions = request["proposed_actions"]
    selected = original_actions[0]
    edited_description = "Use this revised cleaner follow-up draft."

    reconfirmation = graph.invoke(
        Command(
            resume={
                "decision": "edit",
                "action_id": selected["action_id"],
                "edited_description": edited_description,
            }
        ),
        config=config,
    )
    reconfirmation_request = reconfirmation["__interrupt__"][0].value
    edited = next(
        action
        for action in reconfirmation_request["proposed_actions"]
        if action["action_id"] == selected["action_id"]
    )

    assert reconfirmation["human_decision"]["decision"] == "edit"
    assert reconfirmation["human_decision"]["review_complete"] is False
    assert reconfirmation_request["question"].startswith("Reconfirm")
    assert edited["description"] == edited_description
    assert edited["property_id"] == selected["property_id"]
    assert edited["action_type"] == selected["action_type"]
    assert edited["source_finding_ids"] == selected["source_finding_ids"]
    assert edited["executed"] is False

    completed = graph.invoke(
        Command(
            resume={
                "decision": "approve",
                "action_id": selected["action_id"],
            }
        ),
        config=config,
    )

    assert completed["human_decision"]["decision"] == "approve"
    assert completed["human_decision"]["review_complete"] is True
    assert (
        completed["human_decision"]["reviewed_actions"][0]["description"]
        == edited_description
    )
    assert completed["executed_actions"] == []


def test_invalid_resume_stays_interrupted_with_a_validation_error() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config, _, request = start_review(graph, thread_id="phase-7-invalid")
    action_id = request["proposed_actions"][0]["action_id"]

    still_paused = graph.invoke(
        Command(resume={"decision": "edit", "action_id": action_id}),
        config=config,
    )
    retry_request = still_paused["__interrupt__"][0].value

    assert retry_request["validation_error"].startswith("Invalid human decision")
    assert still_paused["human_decision"] is None
    assert still_paused["executed_actions"] == []

    completed = graph.invoke(
        Command(resume={"decision": "reject", "action_id": action_id}),
        config=config,
    )
    assert completed["human_decision"]["decision"] == "reject"


def test_unknown_action_id_stays_interrupted() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    config, _, _ = start_review(graph, thread_id="phase-7-unknown-action")

    still_paused = graph.invoke(
        Command(resume={"decision": "approve", "action_id": "action:unknown"}),
        config=config,
    )

    retry_request = still_paused["__interrupt__"][0].value
    assert "unknown proposed action_id" in retry_request["validation_error"]
    assert still_paused["human_decision"] is None
    assert still_paused["executed_actions"] == []


def test_phase_7_graph_contains_review_but_no_execution_nodes() -> None:
    graph = build_phase_7_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert "risk_action_gate" in node_names
    assert "human_review" in node_names
    assert not {
        "execute_action",
        "send_guest_message",
        "send_cleaner_message",
        "update_maintenance_status",
    } & node_names
