"""Intent-aware, evidence-grounded user-facing response generation."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from langchain_core.runnables import RunnableLambda

from src.models import ResponseGenerationInput, ResponseGenerationOutput, ReviewDecision


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
TURNOVER_CATEGORIES = {
    "same_day_turnover",
    "cleaner_confirmation_missing",
    "cleaner_declined",
    "turnover_timing_risk",
    "turnover_on_track",
    "cleaning_schedule_missing",
}
GUEST_CATEGORIES = {
    "unanswered_message",
    "early_check_in_request",
    "guest_complaint",
    "guest_maintenance_report",
}
MAINTENANCE_CATEGORIES = {
    "open_maintenance",
    "guest_impacting_maintenance",
    "upcoming_stay_maintenance_risk",
}
BOOKING_CATEGORIES = {
    "arrival",
    "departure",
    "occupancy",
    "reservation_conflict",
    "booking_gap",
}


def _humanize(value: Any) -> str:
    return str(value).replace("_", " ").strip().capitalize()


def _human_summary(value: str) -> str:
    return re.sub(
        r"\b\d{4}-\d{2}-\d{2}\b",
        lambda match: _format_date(match.group()),
        value,
    )


def _confirmation_status(value: Any) -> str:
    status = str(value)
    if status == "pending":
        return "confirmation pending"
    if status == "declined":
        return "confirmation declined"
    return _humanize(status)


def _format_date(value: str | None) -> str:
    if not value:
        return "the requested period"
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{parsed.strftime('%b')} {parsed.day}"


def _format_time(value: str | None) -> str:
    if not value:
        return "not recorded"
    try:
        parsed = datetime.strptime(value, "%H:%M:%S")
    except ValueError:
        return value
    return parsed.strftime("%I:%M %p").lstrip("0")


def _scope_dates(date_scope: str | None) -> tuple[date | None, date | None]:
    if not date_scope:
        return None, None
    try:
        dates = [date.fromisoformat(part) for part in date_scope.split("/")]
    except ValueError:
        return None, None
    return dates[0], dates[-1]


def _date_in_scope(value: str, date_scope: str | None) -> bool:
    start, end = _scope_dates(date_scope)
    if start is None or end is None:
        return True
    try:
        candidate = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return start <= candidate <= end


def _scope_label(date_scope: str | None) -> str:
    start, end = _scope_dates(date_scope)
    if start is None or end is None:
        return "in the requested period"
    if start == end:
        return f"on {_format_date(start.isoformat())}"
    return f"from {_format_date(start.isoformat())} to {_format_date(end.isoformat())}"


def _property_name(state: dict[str, Any], property_id: str) -> str:
    return state.get("property_context", {}).get(property_id, {}).get(
        "name", property_id
    )


def _categories(finding: dict[str, Any]) -> set[str]:
    return set(finding.get("categories", []))


def _attention_findings(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            finding
            for finding in state.get("operational_findings", [])
            if finding.get("requires_attention")
        ],
        key=lambda finding: (
            finding.get("priority_rank", 999),
            -SEVERITY_RANK.get(finding.get("severity", "low"), 0),
        ),
    )


def _finding_for_property(
    state: dict[str, Any],
    property_id: str,
    relevant_categories: set[str],
) -> dict[str, Any] | None:
    return next(
        (
            finding
            for finding in _attention_findings(state)
            if finding.get("property_id") == property_id
            and _categories(finding).intersection(relevant_categories)
        ),
        None,
    )


def _action_for_finding(
    state: dict[str, Any],
    finding: dict[str, Any] | None,
    *,
    target_record_id: str | None = None,
) -> dict[str, Any] | None:
    finding_source_ids = set((finding or {}).get("source_finding_ids", []))
    for action in state.get("proposed_actions", []):
        if target_record_id and action.get("target_record_id") == target_record_id:
            return action
        if finding_source_ids.intersection(action.get("source_finding_ids", [])):
            return action
    return None


def _approval_copy(state: dict[str, Any], action: dict[str, Any] | None) -> str | None:
    if action is None or not state.get("requires_human_review", False):
        return None
    description = action.get("description", "Review the proposed action.")
    target_id = action.get("target_record_id")
    tool_name = action.get("tool_name")
    if tool_name == "send_guest_message":
        guest = state.get("guest_message_context", {}).get(target_id, {}).get(
            "guest_name", "the guest"
        )
        return f"Waiting for approval: send “{description}” to {guest}."
    if tool_name == "send_cleaner_message":
        cleaner = state.get("cleaning_context", {}).get(target_id, {}).get(
            "cleaner_name", "the assigned cleaner"
        )
        return f"Waiting for approval: send “{description}” to {cleaner}."
    return f"Waiting for approval: {description}"


def _why_it_matters(state: dict[str, Any], finding: dict[str, Any]) -> str:
    property_id = finding.get("property_id", "")
    categories = _categories(finding)
    if categories.intersection(TURNOVER_CATEGORIES):
        cleaning = next(
            (
                item
                for item in state.get("cleaning_context", {}).values()
                if item.get("property_id") == property_id
            ),
            None,
        )
        if cleaning:
            next_reservation = state.get("reservation_context", {}).get(
                cleaning.get("next_reservation_id"), {}
            )
            if next_reservation:
                return (
                    "The cleaning target is "
                    f"{_format_time(cleaning.get('target_complete_time'))} before a "
                    f"{_format_time(next_reservation.get('check_in_time'))} check-in."
                )
            return (
                "The cleaning target is "
                f"{_format_time(cleaning.get('target_complete_time'))}."
            )
    if categories.intersection(MAINTENANCE_CATEGORIES | GUEST_CATEGORIES):
        ticket = next(
            (
                item
                for item in state.get("maintenance_context", {}).values()
                if item.get("property_id") == property_id
                and item.get("status") != "resolved"
            ),
            None,
        )
        if ticket and ticket.get("guest_impact"):
            return "The issue is affecting a guest."
        message = next(
            (
                item
                for item in state.get("guest_message_context", {}).values()
                if item.get("property_id") == property_id
                and item.get("requires_response")
                and item.get("responded_at") is None
            ),
            None,
        )
        if message:
            return f"{message.get('guest_name', 'A guest')} is waiting for a response."
    severity = _humanize(finding.get("severity", "unknown"))
    return f"This is recorded as {severity} severity."


def _secondary_heads_up(
    state: dict[str, Any],
    relevant_categories: set[str],
) -> str:
    secondary = [
        finding
        for finding in _attention_findings(state)
        if not _categories(finding).intersection(relevant_categories)
    ][:3]
    notes = [
        f"- **{_property_name(state, finding.get('property_id', ''))}** — "
        f"{_human_summary(finding.get('summary', 'Operational attention is required.'))}"
        for finding in secondary
    ]
    if not state.get("analysis_complete", True):
        notes.append(
            "- Analysis incomplete: some operational data could not be checked, "
            "so this is not an all-clear."
        )
    return "\n\n### Heads up\n" + "\n".join(notes) if notes else ""


def _arrivals_response(state: dict[str, Any]) -> str:
    arrivals = sorted(
        [
            reservation
            for reservation in state.get("reservation_context", {}).values()
            if reservation.get("status") == "confirmed"
            and _date_in_scope(
                reservation.get("check_in_date", ""), state.get("date_scope")
            )
        ],
        key=lambda item: (item.get("check_in_date", ""), item.get("check_in_time", "")),
    )
    scope = _scope_label(state.get("date_scope"))
    if not arrivals:
        answer = f"No guest arrivals are scheduled {scope}."
    else:
        noun = "arrival is" if len(arrivals) == 1 else "arrivals are"
        answer = f"{len(arrivals)} {noun} scheduled {scope}."
        answer += "\n\n" + "\n".join(
            f"- **{_property_name(state, item['property_id'])}** — "
            f"{item['guest_name']}, {_format_time(item.get('check_in_time'))}, "
            f"{item['guest_count']} {'guest' if item['guest_count'] == 1 else 'guests'}"
            for item in arrivals
        )
    return answer + _secondary_heads_up(state, BOOKING_CATEGORIES)


def _daily_attention_response(state: dict[str, Any]) -> str:
    findings = _attention_findings(state)
    needs_action = [
        finding
        for finding in findings
        if SEVERITY_RANK.get(finding.get("severity", "low"), 0) >= 3
    ]
    watch = [finding for finding in findings if finding not in needs_action]
    scope = _scope_label(state.get("date_scope"))
    if needs_action:
        noun = (
            "Needs Action item requires"
            if len(needs_action) == 1
            else "Needs Action items require"
        )
        answer = f"{len(needs_action)} {noun} attention {scope}."
        rows = []
        for finding in needs_action:
            action = _action_for_finding(state, finding)
            row = (
                f"- **{_property_name(state, finding['property_id'])}** — "
                f"{_human_summary(finding['summary'])} **Why it matters:** "
                f"{_why_it_matters(state, finding)} **Next:** "
                f"{finding.get('recommended_next_action') or 'Review this item.'}"
            )
            approval = _approval_copy(state, action)
            if approval:
                row += f" {approval}"
            rows.append(row)
        answer += "\n\n" + "\n".join(rows)
    else:
        answer = f"No properties need immediate action {scope}."
    heads_up: list[str] = []
    if watch:
        heads_up.append(
            f"{len(watch)} Watch {'item' if len(watch) == 1 else 'items'}:"
        )
        heads_up.extend(
            f"- **{_property_name(state, finding['property_id'])}** — "
            f"{_human_summary(finding['summary'])}"
            for finding in watch
        )
    if not state.get("analysis_complete", True):
        heads_up.append(
            "- Analysis incomplete: some operational data could not be checked, "
            "so this is not an all-clear."
        )
    if heads_up:
        answer += "\n\n### Heads up\n" + "\n".join(heads_up)
    return answer


def _turnover_response(state: dict[str, Any]) -> str:
    relevant_findings = [
        finding
        for finding in _attention_findings(state)
        if _categories(finding).intersection(TURNOVER_CATEGORIES)
    ]
    risky_property_ids = {finding["property_id"] for finding in relevant_findings}
    cleanings = sorted(
        [
            cleaning
            for cleaning in state.get("cleaning_context", {}).values()
            if cleaning.get("confirmation_status") in {"pending", "declined"}
            or cleaning.get("property_id") in risky_property_ids
        ],
        key=lambda item: (item.get("scheduled_date", ""), item.get("property_id", "")),
    )
    missing_schedule_ids = risky_property_ids.difference(
        cleaning.get("property_id") for cleaning in cleanings
    )
    risk_count = len({item.get("property_id") for item in cleanings} | missing_schedule_ids)
    scope = _scope_label(state.get("date_scope"))
    if risk_count == 0:
        answer = f"No cleaning or turnover risks were found {scope}."
    else:
        noun = "property has" if risk_count == 1 else "properties have"
        answer = f"{risk_count} {noun} a cleaning or turnover risk {scope}."
        rows: list[str] = []
        for cleaning in cleanings:
            checkout = state.get("reservation_context", {}).get(
                cleaning.get("checkout_reservation_id"), {}
            )
            arrival = state.get("reservation_context", {}).get(
                cleaning.get("next_reservation_id"), {}
            )
            finding = _finding_for_property(
                state, cleaning["property_id"], TURNOVER_CATEGORIES
            )
            action = _action_for_finding(
                state, finding, target_record_id=cleaning.get("id")
            )
            next_step = (
                (finding or {}).get("recommended_next_action")
                or "Review the turnover schedule."
            )
            row = (
                f"- **{_property_name(state, cleaning['property_id'])}** — "
                f"Checkout {_format_time(checkout.get('check_out_time'))}; "
                f"cleaning target {_format_time(cleaning.get('target_complete_time'))}; "
                f"next check-in {_format_time(arrival.get('check_in_time'))}; "
                f"{_confirmation_status(cleaning.get('confirmation_status'))}. "
                f"**Next:** {next_step}"
            )
            approval = _approval_copy(state, action)
            if approval:
                row += f" {approval}"
            rows.append(row)
        for property_id in sorted(missing_schedule_ids):
            finding = _finding_for_property(state, property_id, TURNOVER_CATEGORIES)
            rows.append(
                f"- **{_property_name(state, property_id)}** — No cleaning schedule is "
                "recorded. **Next:** "
                f"{(finding or {}).get('recommended_next_action') or 'Review turnover coverage.'}"
            )
        answer += "\n\n" + "\n".join(rows)
    return answer + _secondary_heads_up(state, TURNOVER_CATEGORIES)


def _guest_messages_response(state: dict[str, Any]) -> str:
    messages = sorted(
        [
            message
            for message in state.get("guest_message_context", {}).values()
            if message.get("direction") == "inbound"
            and message.get("requires_response")
            and message.get("responded_at") is None
        ],
        key=lambda item: item.get("received_at", ""),
    )
    scope = _scope_label(state.get("date_scope"))
    if not messages:
        answer = f"No guests are waiting for a reply {scope}."
    else:
        noun = "guest is" if len(messages) == 1 else "guests are"
        answer = f"{len(messages)} {noun} waiting for a reply {scope}."
        rows = []
        for message in messages:
            body = " ".join(str(message.get("body", "")).split())
            if len(body) > 120:
                body = body[:117].rstrip() + "…"
            action = _action_for_finding(
                state,
                _finding_for_property(state, message["property_id"], GUEST_CATEGORIES),
                target_record_id=message.get("id"),
            )
            approval = _approval_copy(state, action)
            approval_status = approval or "No reply is waiting for approval."
            rows.append(
                f"- **{message['guest_name']} · "
                f"{_property_name(state, message['property_id'])}** — "
                f"{_humanize(message.get('urgency'))} urgency. “{body}” "
                f"{approval_status}"
            )
        answer += "\n\n" + "\n".join(rows)
    return answer + _secondary_heads_up(state, GUEST_CATEGORIES)


def _maintenance_response(state: dict[str, Any]) -> str:
    tickets = sorted(
        [
            ticket
            for ticket in state.get("maintenance_context", {}).values()
            if ticket.get("status") != "resolved"
        ],
        key=lambda item: (
            -SEVERITY_RANK.get(item.get("severity", "low"), 0),
            item.get("created_at", ""),
        ),
    )
    property_count = len({ticket.get("property_id") for ticket in tickets})
    scope = _scope_label(state.get("date_scope"))
    if not tickets:
        answer = f"No active maintenance issues were found {scope}."
    else:
        noun = "property has" if property_count == 1 else "properties have"
        answer = f"{property_count} {noun} active maintenance issues {scope}."
        rows = []
        for ticket in tickets:
            finding = _finding_for_property(
                state, ticket["property_id"], MAINTENANCE_CATEGORIES
            )
            action = _action_for_finding(
                state, finding, target_record_id=ticket.get("id")
            )
            next_step = (
                (finding or {}).get("recommended_next_action")
                or "No recommended next step is recorded."
            )
            row = (
                f"- **{_property_name(state, ticket['property_id'])}** — "
                f"{ticket['summary']}; {_humanize(ticket.get('severity'))} severity; "
                f"guest impact: {'Yes' if ticket.get('guest_impact') else 'No'}; "
                f"status: {_humanize(ticket.get('status'))}. **Next:** {next_step}"
            )
            approval = _approval_copy(state, action)
            if approval:
                row += f" {approval}"
            rows.append(row)
        answer += "\n\n" + "\n".join(rows)
    return answer + _secondary_heads_up(state, MAINTENANCE_CATEGORIES)


def _property_status_response(state: dict[str, Any]) -> str:
    property_id = next(
        iter(state.get("property_scope") or state.get("property_context", {})), ""
    )
    name = _property_name(state, property_id)
    findings = [
        finding
        for finding in _attention_findings(state)
        if finding.get("property_id") == property_id
    ]
    highest_severity = max(
        (SEVERITY_RANK.get(finding.get("severity", "low"), 0) for finding in findings),
        default=0,
    )
    if not state.get("analysis_complete", True):
        answer = (
            f"{name} is at risk because the readiness analysis is incomplete; "
            "some required operational data could not be checked. This is not an "
            "all-clear."
        )
    elif highest_severity >= 3:
        summary = _human_summary(findings[0]["summary"]).rstrip(".").lower()
        answer = f"{name} needs action because {summary}."
    elif findings:
        summary = _human_summary(findings[0]["summary"]).rstrip(".").lower()
        answer = f"{name} is at risk because {summary}."
    else:
        answer = (
            f"{name} is ready; no active operational issues were found "
            "in the requested scope."
        )
    if findings:
        rows = []
        for finding in findings:
            row = (
                f"- **Why:** {_human_summary(finding['summary'])} **Next:** "
                f"{finding.get('recommended_next_action') or 'Review this item.'}"
            )
            approval = _approval_copy(state, _action_for_finding(state, finding))
            if approval:
                row += f" {approval}"
            rows.append(row)
        answer += "\n\n" + "\n".join(rows)
    return answer


def _response_kind(state: dict[str, Any]) -> str:
    intent = state.get("intent")
    query = str(state.get("host_query", "")).casefold()
    if intent == "risk_assessment" and any(
        term in query for term in ("clean", "cleaner", "turnover")
    ):
        return "turnover"
    if intent == "general_operations" and any(
        term in query for term in ("checking in", "check in", "check-in")
    ):
        return "arrivals"
    if (
        len(state.get("property_scope", [])) == 1
        and intent
        in {
            "daily_briefing",
            "risk_assessment",
            "general_operations",
            "turnover_operations",
        }
        and any(term in query for term in ("status", "ready", "readiness"))
    ):
        return "property_status"
    return {
        "booking_operations": "arrivals",
        "guest_communications": "guest_messages",
        "turnover_operations": "turnover",
        "maintenance_operations": "maintenance",
        "daily_briefing": "daily_attention",
        "risk_assessment": "daily_attention",
        "general_operations": "daily_attention",
    }.get(intent, "daily_attention")


def format_stayops_response(state: dict[str, Any]) -> str:
    """Answer the routed question from structured state without inventing facts."""

    formatter = {
        "arrivals": _arrivals_response,
        "daily_attention": _daily_attention_response,
        "turnover": _turnover_response,
        "guest_messages": _guest_messages_response,
        "maintenance": _maintenance_response,
        "property_status": _property_status_response,
    }[_response_kind(state)]
    return formatter(state)


class ResponseGenerator:
    """Render an intent-specific host response after workflow completion."""

    def __init__(self) -> None:
        self._runnable = RunnableLambda(self._generate)

    def invoke(self, payload: dict) -> ResponseGenerationOutput:
        return self._runnable.invoke(payload)

    @staticmethod
    def _generate(payload: dict) -> ResponseGenerationOutput:
        context = ResponseGenerationInput.model_validate(payload)
        if context.intent:
            return ResponseGenerationOutput(
                final_response=format_stayops_response(context.model_dump(mode="json"))
            )
        outcome = ResponseGenerator._outcome(context)
        return ResponseGenerationOutput(
            final_response=f"{context.synthesis_briefing}\n\n{outcome}"
        )

    @staticmethod
    def _outcome(context: ResponseGenerationInput) -> str:
        decision = context.human_decision
        if not context.requires_human_review:
            return "No approval was required and no simulated action was performed."
        if decision is None or not decision.review_complete:
            return "Approval is still pending; no simulated action was performed."
        if decision.decision == ReviewDecision.REJECT:
            return "The proposed action was rejected. No simulated action was performed."
        if context.executed_actions:
            count = len(context.executed_actions)
            noun = "action" if count == 1 else "actions"
            outcome = f"Approved: {count} simulated {noun} completed."
            if context.action_execution_errors:
                failure_count = len(context.action_execution_errors)
                outcome += f" {failure_count} additional action could not be completed."
            return outcome
        if context.action_execution_errors:
            return (
                "Approval was recorded, but the simulated action could not be completed. "
                "Review the error before retrying."
            )
        if context.action_attempts:
            return (
                "Approval was recorded, but the simulated action did not complete. "
                "Review the attempt before retrying."
            )
        return "The review was approved. No simulated change was needed."
