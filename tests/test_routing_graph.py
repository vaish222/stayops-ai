"""Phase 2 LangGraph state initialization and routing workflow tests."""

from __future__ import annotations

from datetime import date
from typing import get_type_hints

from src.graph import StayOpsState, build_routing_graph, create_initial_state


REFERENCE_DATE = date(2026, 8, 28)


def test_initial_state_populates_every_declared_field() -> None:
    state = create_initial_state(
        "What needs attention today?",
        request_id="request-test-001",
    )

    assert set(state) == set(get_type_hints(StayOpsState))
    assert state["request_id"] == "request-test-001"
    assert state["host_query"] == "What needs attention today?"
    assert state["property_scope"] == []
    assert state["human_decision"] is None
    assert state["requires_human_review"] is False
    assert state["analysis_complete"] is True
    assert state["unavailable_sources"] == []
    assert state["final_response"] == ""


def test_initial_states_do_not_share_mutable_collections() -> None:
    first = create_initial_state("First request", request_id="request-1")
    second = create_initial_state("Second request", request_id="request-2")

    first["errors"].append({"message": "first only"})

    assert second["errors"] == []


def test_routing_graph_updates_only_router_owned_fields() -> None:
    graph = build_routing_graph(reference_date=REFERENCE_DATE)
    initial_state = create_initial_state(
        "Handle the cleaning issue at Lake House today.",
        request_id="request-graph-001",
    )

    result = graph.invoke(initial_state)

    assert result["request_id"] == "request-graph-001"
    assert result["host_query"] == initial_state["host_query"]
    assert result["intent"] == "turnover_operations"
    assert result["property_scope"] == ["prop_lake_house"]
    assert result["date_scope"] == "2026-08-28"
    assert result["write_requested"] is True
    assert result["booking_findings"] == []
    assert result["guest_findings"] == []
    assert result["proposed_actions"] == []
    assert result["executed_actions"] == []
    assert result["final_response"] == ""


def test_phase_2_graph_contains_no_specialist_nodes() -> None:
    graph = build_routing_graph(reference_date=REFERENCE_DATE)
    node_names = set(graph.get_graph().nodes)

    assert "request_router" in node_names
    assert not {
        "booking_agent",
        "guest_agent",
        "turnover_agent",
        "maintenance_agent",
        "operations_synthesizer",
    } & node_names
