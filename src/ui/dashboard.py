"""Stateful dashboard controller and pure Phase 9 presentation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from src.graph import build_phase_8_graph, create_initial_state
from src.tools import SimulatedOperationsStore


OPERATING_DATE = date(2026, 8, 28)
DEFAULT_DAILY_QUERY = "What needs my attention today?"


class PropertyHealth(StrEnum):
    NEEDS_ATTENTION = "needs_attention"
    WATCH = "watch"
    READY = "ready"


@dataclass(frozen=True)
class PropertySummary:
    property_id: str
    name: str
    location: str
    health: PropertyHealth
    issue_count: int
    headline: str


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def incomplete_analysis_message(result: dict[str, Any]) -> str | None:
    """Return a host-facing warning when required source data was unavailable."""

    sources = result.get("unavailable_sources", [])
    if result.get("analysis_complete", True) and not sources:
        return None
    readable_sources = ", ".join(
        str(source).removeprefix("get_").replace("_", " ")
        for source in sources
    ) or "required operational data"
    return (
        f"Analysis incomplete: {readable_sources} remained unavailable after retry. "
        "Findings are partial; absence of findings is not an all-clear."
    )


def _attention_findings(
    result: dict[str, Any],
    property_id: str,
) -> list[dict[str, Any]]:
    findings = [
        finding
        for finding in result.get("operational_findings", [])
        if finding.get("property_id") == property_id
        and finding.get("requires_attention")
    ]
    return sorted(
        findings,
        key=lambda finding: (
            -SEVERITY_RANK.get(finding.get("severity", "low"), 0),
            finding.get("priority_rank", 999),
        ),
    )


def build_property_summaries(result: dict[str, Any]) -> list[PropertySummary]:
    """Derive one stable operational health summary per loaded property."""

    summaries: list[PropertySummary] = []
    analysis_incomplete = not result.get("analysis_complete", True)
    for property_id, property_record in result.get("property_context", {}).items():
        findings = _attention_findings(result, property_id)
        highest_rank = max(
            (
                SEVERITY_RANK.get(finding.get("severity", "low"), 0)
                for finding in findings
            ),
            default=0,
        )
        if highest_rank >= SEVERITY_RANK["high"]:
            health = PropertyHealth.NEEDS_ATTENTION
        elif findings:
            health = PropertyHealth.WATCH
        elif analysis_incomplete:
            health = PropertyHealth.WATCH
        else:
            health = PropertyHealth.READY
        summaries.append(
            PropertySummary(
                property_id=property_id,
                name=property_record.get("name", property_id),
                location=property_record.get("location", "Location unavailable"),
                health=health,
                issue_count=len(findings),
                headline=(
                    findings[0].get("summary", "Operational review required.")
                    if findings
                    else (
                        "Analysis incomplete; verify unavailable source data."
                        if analysis_incomplete
                        else "No active issues in today's briefing."
                    )
                ),
            )
        )
    return sorted(summaries, key=lambda summary: summary.name)


def count_property_health(
    summaries: list[PropertySummary],
) -> dict[PropertyHealth, int]:
    return {
        health: sum(summary.health == health for summary in summaries)
        for health in PropertyHealth
    }


def evidence_for_action(
    action: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only evidence from findings that support the selected action."""

    source_ids = set(action.get("source_finding_ids", []))
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for finding in findings:
        if not source_ids.intersection(finding.get("source_finding_ids", [])):
            continue
        for item in finding.get("evidence", []):
            key = (
                item.get("source", "unknown"),
                tuple(item.get("record_ids", [])),
                item.get("fact", ""),
            )
            if key not in seen:
                seen.add(key)
                evidence.append(item)
    return evidence


class DashboardController:
    """Keep one graph/checkpointer alive across Streamlit script reruns."""

    def __init__(
        self,
        *,
        graph: Any | None = None,
        reference_date: date = OPERATING_DATE,
        thread_id_factory: Callable[[], str] | None = None,
        runtime_store: SimulatedOperationsStore | None = None,
    ) -> None:
        self.runtime_store = runtime_store or SimulatedOperationsStore(
            clock=lambda: datetime.combine(
                reference_date,
                time(hour=23, minute=59),
                tzinfo=timezone.utc,
            )
        )
        self.graph = (
            graph
            if graph is not None
            else build_phase_8_graph(
                reference_date=reference_date,
                runtime_store=self.runtime_store,
            )
        )
        self._thread_id_factory = thread_id_factory or (
            lambda: f"stayops-ui-{uuid4()}"
        )
        self.daily_result: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None
        self.thread_id: str | None = None
        self.daily_thread_id: str | None = None
        self.last_query: str = ""

    def load_daily_briefing(self) -> dict[str, Any]:
        result = self.run_query(DEFAULT_DAILY_QUERY)
        self.daily_result = result
        self.daily_thread_id = self.thread_id
        return result

    def run_query(self, query: str) -> dict[str, Any]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Ask StayOps requires a non-empty query")
        self.thread_id = self._thread_id_factory()
        self.config = {"configurable": {"thread_id": self.thread_id}}
        self.last_query = normalized
        self.result = self.graph.invoke(
            create_initial_state(normalized, request_id=self.thread_id),
            config=self.config,
        )
        return self.result

    @property
    def pending_review(self) -> dict[str, Any] | None:
        if self.result is None:
            return None
        interrupts = self.result.get("__interrupt__", ())
        return interrupts[0].value if interrupts else None

    def resume_review(
        self,
        decision: str,
        *,
        action_id: str | None = None,
        edited_description: str | None = None,
    ) -> dict[str, Any]:
        if self.pending_review is None or self.config is None:
            raise RuntimeError("there is no interrupted review to resume")
        response: dict[str, Any] = {"decision": decision}
        if action_id is not None:
            response["action_id"] = action_id
        if edited_description is not None:
            response["edited_description"] = edited_description
        self.result = self.graph.invoke(
            Command(resume=response),
            config=self.config,
        )
        if self.thread_id == self.daily_thread_id:
            self.daily_result = self.result
        return self.result
