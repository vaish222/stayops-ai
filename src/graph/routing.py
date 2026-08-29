"""The Phase 2 LangGraph workflow containing only request routing."""

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from src.agents import RequestRouter
from src.graph.state import StayOpsState


def request_router_node(
    state: StayOpsState,
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
) -> dict[str, str | list[str] | bool | None]:
    """Return only the state fields owned by the request router."""

    decision = (router or RequestRouter()).route(
        state["host_query"],
        reference_date=reference_date,
    )
    return decision.model_dump(mode="json")


def build_routing_graph(
    *,
    router: RequestRouter | None = None,
    reference_date: date | None = None,
):
    """Compile the Phase 2 graph: START -> request_router -> END."""

    configured_router = router or RequestRouter()

    def route_node(state: StayOpsState) -> dict[str, str | list[str] | bool | None]:
        return request_router_node(
            state,
            router=configured_router,
            reference_date=reference_date,
        )

    graph_builder = StateGraph(StayOpsState)
    graph_builder.add_node("request_router", route_node)
    graph_builder.add_edge(START, "request_router")
    graph_builder.add_edge("request_router", END)
    return graph_builder.compile(name="stayops_phase_2_routing")
