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
from src.time_context import current_operating_date
from src.tools import SimulatedOperationsStore


DEFAULT_DAILY_QUERY = "What needs my attention today?"


class PropertyHealth(StrEnum):
    NEEDS_ATTENTION = "needs_attention"
    WATCH = "watch"
    READY = "ready"


class ActivityStatus(StrEnum):
    """User-facing execution state for one activity timeline step."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NOT_NEEDED = "not_needed"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    FALLBACK = "fallback"
    REJECTED = "rejected"


@dataclass
class ActivityStep:
    """One stable row in the live Agent Activity timeline."""

    key: str
    label: str
    status: ActivityStatus
    detail: str


@dataclass(frozen=True)
class PropertySummary:
    property_id: str
    name: str
    location: str
    health: PropertyHealth
    issue_count: int
    headline: str


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

ACTIVITY_STEP_LABELS = (
    ("request_router", "Request Router"),
    ("load_context", "Context"),
    ("booking_agent", "Booking"),
    ("guest_agent", "Guest"),
    ("turnover_agent", "Turnover"),
    ("maintenance_agent", "Maintenance"),
    ("operations_synthesizer", "Operations Synthesizer"),
    ("risk_action_gate", "Safety Gate"),
    ("human_review", "Human Approval"),
    ("action", "Simulated Action"),
    ("response_generator", "Response"),
)
SPECIALIST_ACTIVITY_KEYS = {
    "booking": "booking_agent",
    "guest": "guest_agent",
    "turnover": "turnover_agent",
    "maintenance": "maintenance_agent",
}
TERMINAL_ACTIVITY_STATUSES = {
    ActivityStatus.COMPLETED,
    ActivityStatus.NOT_NEEDED,
    ActivityStatus.FAILED,
    ActivityStatus.FALLBACK,
    ActivityStatus.REJECTED,
}


def incomplete_analysis_message(result: dict[str, Any]) -> str | None:
    """Return a host-facing warning when the operational run was incomplete."""

    sources = result.get("unavailable_sources", [])
    if result.get("analysis_complete", True) and not sources:
        return None
    if not sources and result.get("synthesis_complete") is False:
        return (
            "Analysis incomplete: operations synthesis could not be completed. "
            "Findings are incomplete; absence of findings is not an all-clear."
        )
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
        reference_date: date | None = None,
        thread_id_factory: Callable[[], str] | None = None,
        runtime_store: SimulatedOperationsStore | None = None,
    ) -> None:
        self.reference_date = reference_date
        self.runtime_store = runtime_store or (
            SimulatedOperationsStore(
                clock=lambda: datetime.combine(
                    reference_date,
                    time(hour=23, minute=59),
                    tzinfo=timezone.utc,
                )
            )
            if reference_date is not None
            else SimulatedOperationsStore()
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
        self.daily_config: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None
        self.thread_id: str | None = None
        self.daily_thread_id: str | None = None
        self.last_query: str = ""
        self.has_user_query: bool = False
        self.activity_steps: dict[str, ActivityStep] = {}
        self.activity_running: bool = False
        self._selected_activity_specialists: set[str] = set()

    def load_daily_briefing(
        self,
        dashboard_date: date | None = None,
    ) -> dict[str, Any]:
        """Refresh dashboard data without replacing an active user answer."""

        target_date = (
            dashboard_date
            or self.reference_date
            or current_operating_date()
        )
        dashboard_query = (
            f"What needs my attention on {target_date.isoformat()}?"
        )
        preserve_active_query = self.has_user_query
        active_state = (
            self.result,
            self.config,
            self.thread_id,
            self.last_query,
            self.has_user_query,
        )
        result = self.run_query(dashboard_query, user_initiated=False)
        self.daily_result = result
        self.daily_thread_id = self.thread_id
        self.daily_config = self.config
        if preserve_active_query:
            (
                self.result,
                self.config,
                self.thread_id,
                self.last_query,
                self.has_user_query,
            ) = active_state
        return result

    def daily_briefing_needs_refresh_for(self, expected_date: date) -> bool:
        """Return whether dashboard data belongs to another selected date."""

        return (
            self.daily_result is None
            or self.daily_result.get("date_scope") != expected_date.isoformat()
        )

    @property
    def daily_briefing_needs_refresh(self) -> bool:
        """Return whether a dynamic dashboard briefing belongs to an older day."""

        expected_date = self.reference_date or current_operating_date()
        return self.daily_briefing_needs_refresh_for(expected_date)

    def run_query(
        self,
        query: str,
        *,
        user_initiated: bool = True,
        on_activity: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Ask StayOps requires a non-empty query")
        self.thread_id = self._thread_id_factory()
        self.config = {"configurable": {"thread_id": self.thread_id}}
        self.last_query = normalized
        self.has_user_query = user_initiated
        initial_state = create_initial_state(
            normalized,
            request_id=self.thread_id,
        )
        if user_initiated and on_activity is not None:
            self._start_activity()
            on_activity()
            self.result = self._stream_execution(
                initial_state,
                on_activity=on_activity,
            )
            on_activity()
        else:
            self.result = self.graph.invoke(
                initial_state,
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
        on_activity: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if self.pending_review is None or self.config is None:
            raise RuntimeError("there is no interrupted review to resume")
        response: dict[str, Any] = {"decision": decision}
        if action_id is not None:
            response["action_id"] = action_id
        if edited_description is not None:
            response["edited_description"] = edited_description
        command = Command(resume=response)
        if on_activity is not None:
            self._start_review_activity(decision)
            on_activity()
            self.result = self._stream_execution(
                command,
                on_activity=on_activity,
            )
            on_activity()
        else:
            self.result = self.graph.invoke(command, config=self.config)
        if self.thread_id == self.daily_thread_id:
            self.daily_result = self.result
        return self.result

    def _new_activity_steps(self) -> dict[str, ActivityStep]:
        return {
            key: ActivityStep(
                key=key,
                label=label,
                status=ActivityStatus.QUEUED,
                detail="Queued",
            )
            for key, label in ACTIVITY_STEP_LABELS
        }

    def _set_activity(
        self,
        key: str,
        status: ActivityStatus,
        detail: str,
    ) -> None:
        step = self.activity_steps[key]
        step.status = status
        step.detail = detail

    def _start_activity(self) -> None:
        self.activity_steps = self._new_activity_steps()
        self.activity_running = True
        self._selected_activity_specialists = set()
        self.result = None
        self._set_activity(
            "request_router",
            ActivityStatus.RUNNING,
            "Understanding your request…",
        )

    def _start_review_activity(self, decision: str) -> None:
        if not self.activity_steps:
            self.activity_steps = self._new_activity_steps()
            for key in (
                "request_router",
                "load_context",
                "operations_synthesizer",
                "risk_action_gate",
            ):
                self._set_activity(key, ActivityStatus.COMPLETED, "Completed")
            selected = (self.result or {}).get("selected_specialists", [])
            for specialist, key in SPECIALIST_ACTIVITY_KEYS.items():
                status = (
                    ActivityStatus.COMPLETED
                    if specialist in selected
                    else ActivityStatus.NOT_NEEDED
                )
                detail = "Completed" if specialist in selected else "Not needed"
                self._set_activity(key, status, detail)
        self.activity_running = True
        decision_copy = "Recording approval…" if decision == "approve" else "Recording rejection…"
        self._set_activity(
            "human_review",
            ActivityStatus.RUNNING,
            decision_copy,
        )
        self._set_activity("action", ActivityStatus.QUEUED, "Queued")

    def _stream_execution(
        self,
        graph_input: Any,
        *,
        on_activity: Callable[[], None],
    ) -> dict[str, Any]:
        """Stream native LangGraph updates while retaining the invoke result shape."""

        latest_state: dict[str, Any] = {}
        interrupts: tuple[Any, ...] = ()
        try:
            for chunk in self.graph.stream(
                graph_input,
                config=self.config,
                stream_mode=["updates", "values"],
                version="v2",
            ):
                if chunk["type"] == "updates":
                    for node_name, update in chunk["data"].items():
                        self._apply_activity_update(node_name, update or {})
                    on_activity()
                elif chunk["type"] == "values":
                    latest_state = dict(chunk["data"])
                    interrupts = tuple(chunk.get("interrupts", ()))
        except Exception:
            for step in self.activity_steps.values():
                if step.status == ActivityStatus.RUNNING:
                    step.status = ActivityStatus.FAILED
                    step.detail = "Execution failed"
            self.activity_running = False
            on_activity()
            raise

        if interrupts:
            latest_state["__interrupt__"] = interrupts
        self.activity_running = False
        self._finalize_activity(latest_state, interrupts)
        on_activity()
        return latest_state

    def _apply_activity_update(
        self,
        node_name: str,
        update: dict[str, Any] | tuple[Any, ...],
    ) -> None:
        if node_name == "__interrupt__":
            self._set_activity(
                "human_review",
                ActivityStatus.WAITING_APPROVAL,
                "Waiting for your approval",
            )
            return

        if node_name == "request_router":
            selected = update.get("selected_specialists", [])
            self._selected_activity_specialists = set(selected)
            intent = str(update.get("intent", "operations")).replace("_", " ").title()
            self._set_activity(
                node_name,
                ActivityStatus.COMPLETED,
                f"{intent} request recognized",
            )
            self._set_activity(
                "load_context",
                ActivityStatus.RUNNING,
                "Loading operational data…",
            )
            return

        if node_name == "load_context":
            unavailable = update.get("unavailable_sources", [])
            status = ActivityStatus.FALLBACK if unavailable else ActivityStatus.COMPLETED
            detail = (
                f"Partial data · {len(unavailable)} unavailable"
                if unavailable
                else "Operational data loaded"
            )
            self._set_activity(node_name, status, detail)
            selected_set = set(
                update.get(
                    "selected_specialists",
                    self._selected_activity_specialists,
                )
            )
            self._selected_activity_specialists = selected_set
            for specialist, key in SPECIALIST_ACTIVITY_KEYS.items():
                if specialist in selected_set:
                    self._set_activity(
                        key,
                        ActivityStatus.RUNNING,
                        "Analyzing…",
                    )
                else:
                    self._set_activity(
                        key,
                        ActivityStatus.NOT_NEEDED,
                        "Not needed for this request",
                    )
            return

        if node_name in SPECIALIST_ACTIVITY_KEYS.values():
            agent_runs = update.get("agent_runs", [])
            run = agent_runs[-1] if agent_runs else {}
            failed = run.get("status") == "failed"
            finding_fields = {
                "booking_agent": "booking_findings",
                "guest_agent": "guest_findings",
                "turnover_agent": "turnover_findings",
                "maintenance_agent": "maintenance_findings",
            }
            count = len(update.get(finding_fields[node_name], []))
            noun = "finding" if count == 1 else "findings"
            self._set_activity(
                node_name,
                ActivityStatus.FAILED if failed else ActivityStatus.COMPLETED,
                "Failed · See details" if failed else f"{count} {noun}",
            )
            specialist_steps = (
                self.activity_steps[key] for key in SPECIALIST_ACTIVITY_KEYS.values()
            )
            if all(step.status in TERMINAL_ACTIVITY_STATUSES for step in specialist_steps):
                self._set_activity(
                    "operations_synthesizer",
                    ActivityStatus.RUNNING,
                    "Combining findings…",
                )
            return

        if node_name == "operations_synthesizer":
            synthesis_run = update.get("synthesis_run") or {}
            run_status = str(synthesis_run.get("status", "completed"))
            mode = str(synthesis_run.get("mode", "deterministic")).replace("_", " ").title()
            status = (
                ActivityStatus.FALLBACK
                if "fallback" in run_status
                else ActivityStatus.FAILED
                if run_status == "failed"
                else ActivityStatus.COMPLETED
            )
            priority_count = len(update.get("priority_items", []))
            self._set_activity(
                node_name,
                status,
                f"{mode} · {priority_count} prioritized",
            )
            self._set_activity(
                "risk_action_gate",
                ActivityStatus.RUNNING,
                "Checking safety and approval rules…",
            )
            return

        if node_name == "risk_action_gate":
            requires_review = bool(update.get("requires_human_review"))
            review_count = len(update.get("review_reasons", []))
            self._set_activity(
                node_name,
                ActivityStatus.COMPLETED,
                (
                    f"Review required · {review_count} reason(s)"
                    if requires_review
                    else "Checks passed"
                ),
            )
            if requires_review:
                self._set_activity(
                    "human_review",
                    ActivityStatus.RUNNING,
                    "Preparing approval request…",
                )
            else:
                self._set_activity(
                    "human_review",
                    ActivityStatus.NOT_NEEDED,
                    "No approval needed",
                )
                self._set_activity(
                    "action",
                    ActivityStatus.NOT_NEEDED,
                    "No write requested",
                )
                self._set_activity(
                    "response_generator",
                    ActivityStatus.RUNNING,
                    "Preparing your answer…",
                )
            return

        if node_name == "human_review":
            decision = update.get("human_decision", {}).get("decision")
            if decision:
                self._set_activity(
                    node_name,
                    ActivityStatus.COMPLETED,
                    f"{str(decision).title()} recorded",
                )
            return

        if node_name == "execute_approved_actions":
            attempts = update.get("action_attempts", [])
            failed = any(attempt.get("status") == "failed" for attempt in attempts)
            self._set_activity(
                "action",
                ActivityStatus.FAILED if failed else ActivityStatus.COMPLETED,
                "Simulated action failed" if failed else "Simulated action completed",
            )
            return

        if node_name == "record_rejected_action":
            self._set_activity(
                "action",
                ActivityStatus.REJECTED,
                "Action rejected · no write made",
            )
            return

        if node_name == "response_generator":
            self._set_activity(
                node_name,
                ActivityStatus.COMPLETED,
                "Answer ready",
            )

    def _finalize_activity(
        self,
        result: dict[str, Any],
        interrupts: tuple[Any, ...],
    ) -> None:
        if interrupts:
            self._set_activity(
                "human_review",
                ActivityStatus.WAITING_APPROVAL,
                "Waiting for your approval",
            )
            return
        if result.get("response_generated"):
            self._set_activity(
                "response_generator",
                ActivityStatus.COMPLETED,
                "Answer ready",
            )
        for step in self.activity_steps.values():
            if step.status == ActivityStatus.QUEUED:
                step.status = ActivityStatus.NOT_NEEDED
                step.detail = "Not needed"
