"""StayOps AI operations command center."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import streamlit as st

from src.agents.response_generator import format_stayops_response
from src.time_context import current_operating_date
from src.ui import (
    DEFAULT_DAILY_QUERY,
    DashboardController,
    PropertyHealth,
    build_property_summaries,
    count_property_health,
    evidence_for_action,
    incomplete_analysis_message,
)


STATUS_LABELS = {
    PropertyHealth.NEEDS_ATTENTION: "Needs Action",
    PropertyHealth.WATCH: "Watch",
    PropertyHealth.READY: "Ready for Guests",
}
STATUS_ICONS = {
    PropertyHealth.NEEDS_ATTENTION: "●",
    PropertyHealth.WATCH: "◆",
    PropertyHealth.READY: "✓",
}
OPERATIONS_VIEW_TO_TAB = {
    "attention": "Needs Your Attention",
    "guest_messages": "Guest Messages",
    "turnovers": "Turnovers",
    "maintenance": "Maintenance",
    "arrivals": "Arrivals",
}
OPERATIONS_TAB_TO_VIEW = {
    tab_label: view for view, tab_label in OPERATIONS_VIEW_TO_TAB.items()
}
SIDEBAR_NAVIGATION = (
    ("command_center", "Command Center"),
    ("properties", "Properties"),
    ("guest_messages", "Guest Messages"),
    ("turnovers", "Turnovers"),
    ("maintenance", "Maintenance"),
    ("approvals", "Approvals"),
)
SIDEBAR_VIEW_TO_LABEL = dict(SIDEBAR_NAVIGATION)
SIDEBAR_LABEL_TO_VIEW = {
    label: view for view, label in SIDEBAR_NAVIGATION
}
VALID_NAVIGATION_VIEWS = {
    *OPERATIONS_VIEW_TO_TAB,
    *(view for view, _ in SIDEBAR_NAVIGATION),
}


def _install_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy: #18324a;
            --navy-soft: #28465d;
            --muted: #667681;
            --cream: #f7f4ec;
            --card: #fffefb;
            --teal: #147d75;
            --teal-dark: #0d625d;
            --coral-bg: #f8d9d4;
            --coral-text: #963f36;
            --amber-bg: #f9e8bd;
            --amber-text: #85580c;
            --mint-bg: #dcefe4;
            --mint-text: #24604d;
            --blue-bg: #dfeaf5;
            --blue-text: #355f7d;
            --line: #dce1dc;
        }
        .stApp { background: var(--cream); color: var(--navy); }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stSidebar"] {
            background: #e7f0ec;
            border-right: 1px solid #cfdbd5;
        }
        .block-container { max-width: 1280px; padding: 1.4rem 2.1rem 3rem; }
        .command-hero {
            padding: 1.65rem 1.8rem;
            border-radius: 20px;
            color: var(--navy);
            background: linear-gradient(120deg, #dcefeb 0%, #edf6f1 100%);
            border: 1px solid #c6ddd7;
            margin-bottom: 1rem;
        }
        .brand-kicker, .section-kicker {
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .16em;
            text-transform: uppercase;
            color: var(--teal-dark);
        }
        .command-hero h1 { font-size: 2.25rem; margin: .24rem 0 .12rem; color: var(--navy); }
        .command-hero p { margin: 0; font-size: 1rem; color: #526a76; }
        .section-heading { font-size: 1.38rem; font-weight: 780; color: var(--navy); margin: .2rem 0 .1rem; }
        .section-copy { color: var(--muted); font-size: .88rem; margin-bottom: .7rem; }
        .section-anchor { scroll-margin-top: 1rem; }
        .status-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.75rem; margin:.3rem 0 1.4rem; }
        .status-card { border:1px solid var(--line); border-radius:15px; padding:.85rem 1rem; background:var(--card); }
        .status-card.coral { background:#fff9f8; border-top:4px solid #db7669; }
        .status-card.amber { background:#fffaf0; border-top:4px solid #d8a33a; }
        .status-card.mint { background:#f6fbf7; border-top:4px solid #6fae91; }
        .status-card.blue { background:#f7fafd; border-top:4px solid #6e9bbd; }
        .status-card .value { font-size:1.6rem; line-height:1.1; font-weight:800; color:var(--navy); }
        .status-card .label { color:var(--muted); font-size:.78rem; font-weight:700; margin-top:.24rem; }
        [data-testid="stMetric"] {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 16px;
            padding: .85rem 1rem;
        }
        [data-testid="stMetricValue"] { color: var(--navy); font-weight: 750; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--card);
            border-radius: 17px;
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: .35rem;
            padding: .24rem .62rem;
            border-radius: 999px;
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .03em;
            text-transform: uppercase;
        }
        .needs_attention { color: var(--coral-text); background: var(--coral-bg); }
        .watch { color: var(--amber-text); background: var(--amber-bg); }
        .ready { color: var(--mint-text); background: var(--mint-bg); }
        .issue-title { font-size: 1.04rem; font-weight: 750; margin: .45rem 0 .2rem; }
        .muted { color: var(--muted); font-size: .88rem; }
        .property-name { font-weight: 750; font-size: 1rem; }
        .attention-card, .property-card, .agent-card, .approval-banner {
            background:var(--card); border:1px solid var(--line); border-radius:16px; padding:1rem 1.05rem;
        }
        .attention-card { border-top:4px solid #df7d70; min-height:164px; padding:.82rem .95rem; }
        .attention-card h3, .property-card h3 { color:var(--navy); font-size:1.03rem; margin:.15rem 0 .35rem; }
        .card-header { display:flex; align-items:center; justify-content:space-between; gap:.5rem; }
        .detail-line { color:#4f626d; font-size:.82rem; margin:.28rem 0; }
        .attention-link { color:var(--teal-dark); font-weight:750; font-size:.84rem; text-decoration:none; }
        .watch-summary { color:var(--amber-text); font-size:.82rem; font-weight:700; margin:-.38rem 0 .72rem; }
        .property-card { min-height:160px; padding:.65rem .72rem; }
        .property-meta { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.4rem; margin:.52rem 0; }
        .property-meta div { background:#f7f8f5; border-radius:9px; padding:.36rem .42rem; font-size:.73rem; color:#526570; }
        .property-meta strong { display:block; color:var(--navy); font-size:.72rem; margin-bottom:.1rem; }
        .approval-banner { background:#fff7e2; border-color:#e7c46f; margin:.45rem 0 1rem; }
        .approval-banner strong { display:block; color:#6f4b0d; margin-bottom:.2rem; }
        .st-key-stayops_answer {
            background:#edf4f9; border-color:#d8e5ee; border-radius:16px;
        }
        .agent-card { min-height:112px; }
        .agent-card strong { color:var(--navy); }
        .agent-count { font-size:1.12rem; font-weight:800; color:var(--teal-dark); margin:.35rem 0 .2rem; }
        .agent-status { color:#526570; font-size:.8rem; line-height:1.35; }
        .flow-arrow { text-align:center; color:#789098; font-size:1.25rem; line-height:1; padding:.15rem; }
        .sidebar-brand { font-size:1.1rem; font-weight:850; color:var(--navy); letter-spacing:.08em; margin:.15rem 0 1rem; }
        .st-key-sidebar_navigation [role="radiogroup"] { gap:.22rem; }
        .st-key-sidebar_navigation label {
            background:transparent !important; border:0 !important; border-radius:9px;
            color:#38525f; padding:.42rem .55rem !important; font-weight:650;
        }
        .st-key-sidebar_navigation label:has(input:checked) {
            background:#d4e7e1 !important; color:var(--teal-dark);
        }
        [data-testid="stRadio"] > div { gap:.4rem; }
        [data-testid="stRadio"] label { background:#fffefb; border:1px solid var(--line); border-radius:999px; padding:.12rem .5rem; }
        div.stButton > button[kind="primary"] {
            background: var(--teal); border-color: var(--teal); font-weight: 700;
        }
        div.stButton > button { border-radius: 10px; font-weight: 650; }
        @media (max-width: 900px) {
            .status-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .property-meta { grid-template-columns:1fr; }
            .block-container { padding-left:1rem; padding-right:1rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _controller() -> DashboardController:
    if "stayops_controller" not in st.session_state:
        st.session_state.stayops_controller = DashboardController()
    controller: DashboardController = st.session_state.stayops_controller
    if controller.daily_briefing_needs_refresh:
        controller.load_daily_briefing()
    return controller


def _requested_view() -> str:
    """Return a validated URL-backed dashboard destination."""

    requested = st.query_params.get("view", "command_center")
    if isinstance(requested, list):
        requested = requested[-1] if requested else "command_center"
    return requested if requested in VALID_NAVIGATION_VIEWS else "command_center"


def _sync_sidebar_view() -> None:
    """Keep deep-link state aligned with the native sidebar selection."""

    selected_label = st.session_state.get("sidebar_navigation")
    selected_view = SIDEBAR_LABEL_TO_VIEW.get(selected_label)
    if selected_view is not None:
        st.query_params["view"] = selected_view


def _render_sidebar_navigation(current_view: str) -> None:
    requested_label = SIDEBAR_VIEW_TO_LABEL.get(
        current_view,
        "Command Center",
    )
    if (
        "sidebar_navigation" not in st.session_state
        or st.session_state.sidebar_navigation != requested_label
    ):
        st.session_state.sidebar_navigation = requested_label
    st.radio(
        "Navigation",
        [label for _, label in SIDEBAR_NAVIGATION],
        key="sidebar_navigation",
        on_change=_sync_sidebar_view,
        label_visibility="collapsed",
    )


def _sync_operations_view() -> None:
    """Keep the URL and sidebar highlight aligned with a manual tab change."""

    selected_tab = st.session_state.get("operations_tab")
    selected_view = OPERATIONS_TAB_TO_VIEW.get(selected_tab)
    if selected_view is not None:
        st.query_params["view"] = selected_view


def _status_pill(health: PropertyHealth) -> str:
    return (
        f'<span class="status-pill {health.value}">'
        f"{STATUS_ICONS[health]} {STATUS_LABELS[health]}</span>"
    )


def _format_time(value: str | None) -> str:
    if not value:
        return "Time not set"
    try:
        return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return value


def _format_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{parsed.strftime('%b')} {parsed.day}"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    readable_time = parsed.strftime("%I:%M %p").lstrip("0")
    return f"{parsed.strftime('%b')} {parsed.day} · {readable_time}"


def _humanize(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value)
    if text == "synthetic_marketplace":
        return "Marketplace"
    return text.replace("_", " ").title()


def _cleaner_display(name: str) -> str:
    return f"Assigned cleaner: {name}"


def _confirmation_display(status: str) -> str:
    if status == "pending":
        return "Confirmation pending"
    return _humanize(status)


def _arrivals_today(result: dict[str, Any]) -> int:
    operating_date = result.get("date_scope")
    return sum(
        item.get("status") == "confirmed"
        and item.get("check_in_date") == operating_date
        for item in result.get("reservation_context", {}).values()
    )


def _context_records(
    result: dict[str, Any],
    source: str,
    record_ids: list[str],
) -> list[dict[str, Any]]:
    field_by_source = {
        "reservations": "reservation_context",
        "guest_messages": "guest_message_context",
        "cleaning_schedule": "cleaning_context",
        "maintenance_tickets": "maintenance_context",
        "property_rules": "property_rule_context",
    }
    context = result.get(field_by_source.get(source, ""), {})
    return [context[record_id] for record_id in record_ids if record_id in context]


def _plain_evidence_lines(
    evidence: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[str]:
    """Translate structured evidence into operator-friendly copy without raw IDs."""

    lines: list[str] = []
    for item in evidence:
        source = str(item.get("source", ""))
        records = _context_records(result, source, item.get("record_ids", []))
        for record in records:
            if source == "reservations":
                lines.append(
                    f"{record['guest_name']}: check-in {record['check_in_date']} at "
                    f"{_format_time(record.get('check_in_time'))}; check-out "
                    f"{record['check_out_date']} at {_format_time(record.get('check_out_time'))}."
                )
            elif source == "guest_messages":
                lines.append(
                    f"{record['guest_name']} wrote: {record['body']}"
                )
            elif source == "cleaning_schedule":
                lines.append(
                    f"{_cleaner_display(record['cleaner_name'])}; "
                    f"{_confirmation_display(record['confirmation_status']).lower()}; "
                    "target completion "
                    f"is {_format_time(record.get('target_complete_time'))}."
                )
            elif source == "maintenance_tickets":
                lines.append(
                    f"{record['summary']} is {record['severity']} severity and "
                    f"{record['status'].replace('_', ' ')}."
                )
            elif source == "property_rules":
                lines.append(
                    f"Standard check-in is {_format_time(record.get('standard_check_in_time'))}; "
                    f"cleaner-ready buffer is {record['cleaner_ready_buffer_minutes']} minutes."
                )
        if not records:
            lines.append("An operational source record supports this finding.")
    return list(dict.fromkeys(lines))


def _section_heading(anchor: str, title: str, copy: str | None = None) -> None:
    copy_markup = f'<div class="section-copy">{escape(copy)}</div>' if copy else ""
    st.markdown(
        f'<div id="{escape(anchor)}" class="section-anchor">'
        f'<div class="section-heading">{escape(title)}</div>{copy_markup}</div>',
        unsafe_allow_html=True,
    )


def _show_notice() -> None:
    notice = st.session_state.pop("stayops_notice", None)
    if notice is None:
        return
    level, message = notice
    getattr(st, level)(message)


def _run_query(controller: DashboardController, query: str) -> None:
    try:
        controller.run_query(query)
    except ValueError as exc:
        st.session_state.stayops_notice = ("warning", str(exc))
    else:
        st.session_state.pop("stayops_notice", None)


def _resume_review(
    controller: DashboardController,
    decision: str,
    action_id: str | None,
    edited_description: str | None = None,
) -> None:
    review = controller.pending_review or {}
    acknowledgement_only = not review.get("proposed_actions")
    previous_execution_count = len(
        (controller.result or {}).get("executed_actions", [])
    )
    selected_action = next(
        (
            action
            for action in review.get("proposed_actions", [])
            if action.get("action_id") == action_id
        ),
        {},
    )
    try:
        result = controller.resume_review(
            decision,
            action_id=action_id,
            edited_description=edited_description,
        )
    except (RuntimeError, ValueError) as exc:
        st.session_state.stayops_notice = ("error", str(exc))
        return
    remaining_review = controller.pending_review
    remaining_count = len(
        (remaining_review or {}).get("proposed_actions", [])
    )
    latest_execution_count = max(
        0,
        len(result.get("executed_actions", [])) - previous_execution_count,
    )
    if decision == "approve" and acknowledgement_only:
        st.session_state.stayops_notice = (
            "success",
            "Incomplete analysis acknowledged. No simulated action was executed.",
        )
    elif decision == "approve":
        tool_name = selected_action.get("tool_name")
        outcome = (
            "Approved and sent — simulation only."
            if tool_name in {"send_guest_message", "send_cleaner_message"}
            else "Approved and updated — simulation only."
            if tool_name == "update_maintenance_status"
            else "Approved — no write was required."
        )
        if latest_execution_count == 0 and selected_action.get("tool_name"):
            outcome = "Approval recorded, but the simulated write did not complete."
        if remaining_count:
            noun = "action" if remaining_count == 1 else "actions"
            outcome += f" {remaining_count} {noun} still need review."
        st.session_state.stayops_notice = ("success", outcome)
    elif decision == "reject" and remaining_count:
        noun = "action" if remaining_count == 1 else "actions"
        st.session_state.stayops_notice = (
            "info",
            f"Action rejected — nothing was sent. {remaining_count} {noun} still need review.",
        )
    elif decision == "edit" and remaining_review is not None:
        st.session_state.stayops_notice = (
            "warning",
            "The edited action is ready for reconfirmation.",
        )
    else:
        st.session_state.pop("stayops_notice", None)


def _urgent_findings(result: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    urgent: list[dict[str, Any]] = []
    seen_properties: set[str] = set()
    for finding in result.get("priority_items", []):
        property_id = finding.get("property_id")
        if (
            not finding.get("requires_attention")
            or finding.get("severity") not in {"high", "critical"}
            or property_id in seen_properties
        ):
            continue
        urgent.append(finding)
        seen_properties.add(property_id)
        if len(urgent) == limit:
            break
    return urgent


def _attention_key_line(
    finding: dict[str, Any],
    result: dict[str, Any],
) -> str:
    categories = set(finding.get("categories", []))
    property_id = finding.get("property_id")
    reservations = [
        item
        for item in result.get("reservation_context", {}).values()
        if item.get("property_id") == property_id
    ]
    cleanings = [
        item
        for item in result.get("cleaning_context", {}).values()
        if item.get("property_id") == property_id
    ]
    if "same_day_turnover" in categories or "turnover_timing_risk" in categories:
        operating_date = result.get("date_scope")
        departure = next(
            (item for item in reservations if item.get("check_out_date") == operating_date),
            None,
        )
        arrival = next(
            (item for item in reservations if item.get("check_in_date") == operating_date),
            None,
        )
        timing = []
        if departure:
            timing.append(f"Checkout {_format_time(departure.get('check_out_time'))}")
        if arrival:
            timing.append(f"Check-in {_format_time(arrival.get('check_in_time'))}")
        if cleanings:
            timing.append(
                "Cleaning "
                f"{_confirmation_display(cleanings[0].get('confirmation_status')).lower()}"
            )
        return " → ".join(timing[:2]) + (f" · {timing[2]}" if len(timing) > 2 else "")
    if categories.intersection(
        {"guest_maintenance_report", "guest_impacting_maintenance"}
    ):
        return "AC not cooling · Guest reply pending"
    if "open_maintenance" in categories:
        ticket = next(
            (
                item
                for item in result.get("maintenance_context", {}).values()
                if item.get("property_id") == property_id
            ),
            None,
        )
        return (
            f"{ticket['summary']} · {_humanize(ticket['status'])}"
            if ticket
            else "Maintenance issue requires review"
        )
    return "Operational issue requires review"


def _attention_copy(finding: dict[str, Any], result: dict[str, Any]) -> tuple[str, str]:
    categories = set(finding.get("categories", []))
    if categories.intersection({"same_day_turnover", "turnover_timing_risk"}):
        cleaning = next(
            (
                item
                for item in result.get("cleaning_context", {}).values()
                if item.get("property_id") == finding.get("property_id")
            ),
            None,
        )
        target = _format_time(cleaning.get("target_complete_time")) if cleaning else "target time"
        return "Turnover at risk", f"Confirm cleaner can complete by {target}."
    if categories.intersection(
        {"guest_maintenance_report", "guest_impacting_maintenance"}
    ):
        return "Guest impacted", "Review guest response and maintenance status."
    if "open_maintenance" in categories:
        return "Maintenance needs attention", "Review repair timing and guest impact."
    return finding["summary"], "Review and handle this issue."


def _render_attention(result: dict[str, Any]) -> None:
    findings = _urgent_findings(result)
    summaries = build_property_summaries(result)
    watch_count = sum(summary.health == PropertyHealth.WATCH for summary in summaries)
    action_noun = "property requires" if len(findings) == 1 else "properties require"
    watch_copy = (
        f" · {watch_count} more {'property is' if watch_count == 1 else 'properties are'} on watch"
        if watch_count
        else ""
    )
    _section_heading(
        "needs-attention",
        "Needs Your Attention",
        f"{len(findings)} {action_noun} action{watch_copy}",
    )
    if not findings:
        st.success("No urgent issues need intervention right now.")
        return
    columns = st.columns(len(findings))
    for column, finding in zip(columns, findings, strict=True):
        property_name = _property_name(result, finding["property_id"])
        issue_title, next_action = _attention_copy(finding, result)
        key_line = _attention_key_line(finding, result)
        with column:
            st.markdown(
                '<div class="attention-card">'
                '<div class="card-header">'
                f'<h3>{escape(property_name)}</h3>'
                f'{_status_pill(PropertyHealth.NEEDS_ATTENTION)}'
                '</div>'
                f'<div class="issue-title">{escape(issue_title)}</div>'
                f'<div class="detail-line">{escape(key_line)}</div>'
                f'<div class="detail-line"><strong>Next:</strong> {escape(next_action)}</div>'
                '<a class="attention-link" href="#approval-center">'
                'Review &amp; Handle →</a>'
                '</div>',
                unsafe_allow_html=True,
            )


def _render_ask_stayops(controller: DashboardController) -> None:
    _section_heading(
        "ask-stayops",
        "Ask StayOps",
        "Ask a question about today’s guests, turnovers, maintenance, or risk.",
    )
    with st.form("ask_stayops", clear_on_submit=True):
        query = st.text_input(
            "Operational question",
            placeholder="What needs my attention today?",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask StayOps", type="primary")
    if submitted:
        _run_query(controller, query)

    quick_prompts = {
        "What's urgent today?": "What's urgent today?",
        "Who's checking in?": "Which guests are arriving today?",
        "Cleaning risks": "What cleaning risks need attention today?",
        "Guests needing replies": "Which guest messages need a reply today?",
    }
    prompt_columns = st.columns(4)
    for column, (label, prompt) in zip(
        prompt_columns, quick_prompts.items(), strict=True
    ):
        if column.button(label, key=f"quick_prompt_{label}", width="stretch"):
            _run_query(controller, prompt)
    _show_notice()
    _render_stayops_answer(controller)


def _property_card_details(
    result: dict[str, Any],
    property_id: str,
) -> tuple[str, str, str]:
    reservations = sorted(
        (
            item
            for item in result.get("reservation_context", {}).values()
            if item.get("property_id") == property_id
            and item.get("status") == "confirmed"
        ),
        key=lambda item: (item["check_in_date"], item["check_in_time"]),
    )
    arrivals = [
        item
        for item in reservations
        if item.get("check_in_date") == result.get("date_scope")
    ]
    departures = [
        item
        for item in reservations
        if item.get("check_out_date") == result.get("date_scope")
    ]
    next_arrival = (
        f"Today, {_format_time(arrivals[0].get('check_in_time'))}"
        if arrivals
        else "No arrival today"
    )
    next_departure = (
        f"Today, {_format_time(departures[0].get('check_out_time'))}"
        if departures
        else "No departure today"
    )
    cleanings = [
        item
        for item in result.get("cleaning_context", {}).values()
        if item.get("property_id") == property_id
    ]
    maintenance = [
        item
        for item in result.get("maintenance_context", {}).values()
        if item.get("property_id") == property_id
    ]
    if cleanings:
        operations = (
            "Cleaning "
            f"{_confirmation_display(cleanings[0]['confirmation_status']).lower()}"
        )
    elif maintenance:
        operations = f"Maintenance {_humanize(maintenance[0]['status'])}"
    else:
        operations = "No active task"
    return next_arrival, next_departure, operations


def _render_portfolio_cards(
    summaries,
    result: dict[str, Any],
    status_filter: str,
) -> None:
    visible = [
        summary
        for summary in summaries
        if status_filter == "All" or STATUS_LABELS[summary.health] == status_filter
    ]
    if not visible:
        st.info("No properties match this status filter.")
        return
    columns = st.columns(2)
    for index, summary in enumerate(visible):
        arrival, departure, operations = _property_card_details(
            result, summary.property_id
        )
        with columns[index % 2]:
            with st.container(border=True):
                st.markdown(
                    '<div class="property-card">'
                    f'<div class="muted">{escape(summary.location)}</div>'
                    f'<h3>{escape(summary.name)}</h3>'
                    f'{_status_pill(summary.health)}'
                    '<div class="property-meta">'
                    f'<div><strong>Next arrival</strong>{escape(arrival)}</div>'
                    f'<div><strong>Departure</strong>{escape(departure)}</div>'
                    f'<div><strong>Property ops</strong>{escape(operations)}</div>'
                    '</div>'
                    f'<div class="detail-line">{escape(summary.headline)}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                st.button(
                    "View property",
                    key=f"view_property_{summary.property_id}",
                    on_click=lambda name=summary.name: st.session_state.update(
                        property_drilldown=name
                    ),
                )


def _render_property_drilldown(
    result: dict[str, Any],
    summary,
) -> None:
    record = result["property_context"][summary.property_id]
    _section_heading("selected-property", summary.name, summary.location)
    st.markdown(_status_pill(summary.health), unsafe_allow_html=True)

    overview_tab, stays_tab, operations_tab = st.tabs(
        ["Overview", "Stays", "Property Ops"]
    )
    with overview_tab:
        c1, c2, c3 = st.columns(3)
        c1.metric("Bedrooms", record["bedrooms"])
        c2.metric("Bathrooms", record["bathrooms"])
        c3.metric("Max guests", record["max_guests"])
        st.write(record["description"])
        rule = next(
            (
                item
                for item in result.get("property_rule_context", {}).values()
                if item.get("property_id") == summary.property_id
            ),
            None,
        )
        if rule is not None:
            st.markdown("**Operating rules**")
            st.write(
                f"Check-in {_format_time(rule['standard_check_in_time'])} · "
                f"Check-out {_format_time(rule['standard_check_out_time'])} · "
                f"Cleaner-ready buffer {rule['cleaner_ready_buffer_minutes']} minutes"
            )
            st.caption(
                f"Early check-in: {_humanize(rule['early_check_in_policy'])} · "
                f"Pets: {_humanize(rule['pets_policy'])}"
            )
            for house_rule in rule.get("house_rules", []):
                st.write(f"• {house_rule}")

    with stays_tab:
        reservations = [
            item
            for item in result.get("reservation_context", {}).values()
            if item.get("property_id") == summary.property_id
        ]
        if reservations:
            st.dataframe(
                [
                    {
                        "Guest": item["guest_name"],
                        "Check-in": _format_date(item["check_in_date"]),
                        "Check-out": _format_date(item["check_out_date"]),
                        "Status": _humanize(item["status"]),
                    }
                    for item in reservations
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No reservations in the current operating scope.")

    with operations_tab:
        cleanings = [
            item
            for item in result.get("cleaning_context", {}).values()
            if item.get("property_id") == summary.property_id
        ]
        maintenance = [
            item
            for item in result.get("maintenance_context", {}).values()
            if item.get("property_id") == summary.property_id
        ]
        st.markdown("**Turnover**")
        if cleanings:
            for item in cleanings:
                st.write(
                    f"{_format_date(item['scheduled_date'])} · "
                    f"{_cleaner_display(item['cleaner_name'])} · "
                    f"{_confirmation_display(item['confirmation_status'])}"
                )
        else:
            st.caption("No cleaning jobs in scope.")
        st.markdown("**Maintenance**")
        if maintenance:
            for item in maintenance:
                st.write(
                    f"{item['summary']} · {_humanize(item['severity'])} · "
                    f"{_humanize(item['status'])}"
                )
        else:
            st.caption("No maintenance tickets in scope.")


def _render_priorities(
    result: dict[str, Any],
    property_id: str | None,
) -> None:
    st.caption("Ranked by operational impact and urgency.")
    properties = result.get("property_context", {})
    findings = [
        finding
        for finding in result.get("priority_items", [])
        if property_id is None or finding.get("property_id") == property_id
    ]
    if not findings:
        st.success("No active issues for this view.")
        return
    for finding in findings:
        prop = properties.get(finding["property_id"], {})
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.caption(
                    f"Priority {finding['priority_rank']} · "
                    f"{prop.get('name', finding['property_id'])}"
                )
                st.markdown(
                    f'<div class="issue-title">{escape(finding["summary"])}</div>',
                    unsafe_allow_html=True,
                )
            with right:
                severity = finding["severity"]
                health = (
                    PropertyHealth.NEEDS_ATTENTION
                    if severity in {"high", "critical"}
                    else PropertyHealth.WATCH
                )
                st.markdown(_status_pill(health), unsafe_allow_html=True)
            if finding.get("recommended_next_action"):
                st.write(f"Next: {finding['recommended_next_action']}")
            evidence_lines = _plain_evidence_lines(
                finding.get("evidence", []), result
            )
            with st.expander("Why StayOps flagged this"):
                for line in evidence_lines:
                    st.write(line)


def _property_name(result: dict[str, Any], property_id: str) -> str:
    return result.get("property_context", {}).get(property_id, {}).get(
        "name", property_id
    )


def _in_property_scope(item: dict[str, Any], property_id: str | None) -> bool:
    return property_id is None or item.get("property_id") == property_id


def _render_messages(result: dict[str, Any], property_id: str | None) -> None:
    messages = [
        item
        for item in result.get("guest_message_context", {}).values()
        if _in_property_scope(item, property_id)
    ]
    if not messages:
        st.info("No guest messages in the current operating scope.")
        return
    st.dataframe(
        [
            {
                "Property": _property_name(result, item["property_id"]),
                "Guest": item["guest_name"],
                "Received": _format_timestamp(item["received_at"]),
                "Direction": _humanize(item["direction"]),
                "Urgency": _humanize(item["urgency"]),
                "Needs response": _humanize(
                    item["requires_response"] and item.get("responded_at") is None
                ),
                "Message": item["body"],
            }
            for item in messages
        ],
        hide_index=True,
        width="stretch",
    )


def _render_cleanings(result: dict[str, Any], property_id: str | None) -> None:
    cleanings = [
        item
        for item in result.get("cleaning_context", {}).values()
        if _in_property_scope(item, property_id)
    ]
    if not cleanings:
        st.info("No cleaning jobs in the current operating scope.")
        return
    st.dataframe(
        [
            {
                "Property": _property_name(result, item["property_id"]),
                "Date": _format_date(item["scheduled_date"]),
                "Assigned cleaner": item["cleaner_name"],
                "Window start": _format_time(item["window_start"]),
                "Target complete": _format_time(item["target_complete_time"]),
                "Confirmation": _confirmation_display(
                    item["confirmation_status"]
                ),
                "Status": _humanize(item["status"]),
                "Contact": (
                    "Reminder sent (simulated)"
                    if "Simulated reminder sent" in (item.get("notes") or "")
                    else "No reminder sent"
                ),
            }
            for item in cleanings
        ],
        hide_index=True,
        width="stretch",
    )


def _render_maintenance(result: dict[str, Any], property_id: str | None) -> None:
    tickets = [
        item
        for item in result.get("maintenance_context", {}).values()
        if _in_property_scope(item, property_id)
    ]
    if not tickets:
        st.info("No active maintenance tickets in the current operating scope.")
        return
    st.dataframe(
        [
            {
                "Property": _property_name(result, item["property_id"]),
                "Issue": item["summary"],
                "Severity": _humanize(item["severity"]),
                "Status": _humanize(item["status"]),
                "Blocks check-in": _humanize(item["blocks_checkin"]),
                "Assigned vendor": item.get("assigned_vendor") or "Unassigned",
            }
            for item in tickets
        ],
        hide_index=True,
        width="stretch",
    )


def _render_upcoming_arrivals(
    result: dict[str, Any],
    property_id: str | None,
) -> None:
    reservations = [
        item
        for item in result.get("reservation_context", {}).values()
        if _in_property_scope(item, property_id) and item.get("status") == "confirmed"
    ]
    if not reservations:
        st.info("No confirmed arrivals in the current operating scope.")
        return
    reservations.sort(key=lambda item: (item["check_in_date"], item["check_in_time"]))
    st.dataframe(
        [
            {
                "Property": _property_name(result, item["property_id"]),
                "Guest": item["guest_name"],
                "Check-in date": _format_date(item["check_in_date"]),
                "Check-in time": _format_time(item["check_in_time"]),
                "Guests": item["guest_count"],
                "Source": _humanize(item["source"]),
            }
            for item in reservations
        ],
        hide_index=True,
        width="stretch",
    )


def _render_operations_views(
    result: dict[str, Any],
    property_id: str | None,
    requested_view: str,
) -> None:
    _section_heading(
        "operations-workspace",
        "Operations Workspace",
        "See the operational details behind every StayOps alert.",
    )
    tab_labels = list(OPERATIONS_VIEW_TO_TAB.values())
    requested_tab = OPERATIONS_VIEW_TO_TAB.get(
        requested_view,
        "Needs Your Attention",
    )
    if (
        "operations_tab" not in st.session_state
        or (
            requested_view in OPERATIONS_VIEW_TO_TAB
            and st.session_state.operations_tab != requested_tab
        )
    ):
        st.session_state.operations_tab = requested_tab
    priorities, messages, cleanings, maintenance, arrivals = st.tabs(
        tab_labels,
        default=requested_tab,
        key="operations_tab",
        on_change=_sync_operations_view,
    )
    with priorities:
        _render_priorities(result, property_id)
    with messages:
        _render_messages(result, property_id)
    with cleanings:
        _render_cleanings(result, property_id)
    with maintenance:
        _render_maintenance(result, property_id)
    with arrivals:
        _render_upcoming_arrivals(result, property_id)


def _approval_explanation(action: dict[str, Any]) -> str:
    tool_name = action.get("tool_name")
    if tool_name == "send_guest_message":
        return "This action will simulate sending a message to the guest."
    if tool_name == "send_cleaner_message":
        return "This action will simulate sending a message to the cleaner."
    if tool_name == "update_maintenance_status":
        return "This action will update the simulated maintenance record."
    return "This operational decision requires your review before StayOps continues."


def _render_review(controller: DashboardController) -> None:
    request = controller.pending_review
    _section_heading(
        "approval-center",
        "Human Approvals",
        "Review every proposed write before it can be simulated.",
    )
    if request is None:
        st.info("No approvals are pending for the latest StayOps request.")
        return
    result = controller.result or controller.daily_result or {}
    st.markdown(
        '<div class="approval-banner">'
        '<strong>Your approval is needed</strong>'
        '<span>StayOps never sends messages or changes operational records without you.</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Simulation mode: no external message is sent. Approved changes are saved "
        "to the local demo runtime and reflected in these screens."
    )
    actions = request.get("proposed_actions", [])
    if not actions:
        st.error("StayOps could not complete this operational check.")
        st.write("Please acknowledge the incomplete analysis before continuing.")
        if st.button(
            "Acknowledge",
            type="primary",
            key=f"acknowledge_{controller.thread_id}",
        ):
            _resume_review(controller, "approve", None)
            st.rerun()
        return

    for action in actions:
        action_id = action["action_id"]
        property_name = _property_name(result, action["property_id"])
        action_label = action["action_type"].replace("_", " ").title()
        tool_name = action.get("tool_name")
        approve_label = (
            "Approve & Send"
            if tool_name in {"send_guest_message", "send_cleaner_message"}
            else "Approve & Update"
            if tool_name == "update_maintenance_status"
            else "Approve"
        )
        with st.container(border=True):
            st.markdown(
                f"### {escape(property_name)}  \n"
                f"**{escape(action_label)}**"
            )
            st.markdown("**Why your approval is required**")
            st.caption(_approval_explanation(action))
            st.markdown("**Proposed action**")
            st.markdown(
                f'<div class="detail-line">{escape(action["description"])}</div>',
                unsafe_allow_html=True,
            )
            supporting = evidence_for_action(action, request.get("findings", []))
            plain_evidence = _plain_evidence_lines(supporting, result)
            with st.expander("Why StayOps suggested this"):
                for line in plain_evidence:
                    st.write(line)
            approve_col, reject_col = st.columns(2)
            if approve_col.button(
                approve_label,
                type="primary",
                width="stretch",
                key=f"approve_{controller.thread_id}_{action_id}",
            ):
                progress_message = (
                    "Approving and sending the simulated message…"
                    if tool_name in {"send_guest_message", "send_cleaner_message"}
                    else "Approving and updating the simulated record…"
                )
                with st.spinner(progress_message):
                    _resume_review(controller, "approve", action_id)
                st.rerun()
            if reject_col.button(
                "Reject",
                width="stretch",
                key=f"reject_{controller.thread_id}_{action_id}",
            ):
                _resume_review(controller, "reject", action_id)
                st.rerun()


def _stayops_answer(controller: DashboardController) -> str:
    result = controller.result
    if result is None:
        return "StayOps has not run yet."
    return format_stayops_response(result)


def _render_stayops_answer(controller: DashboardController) -> None:
    if not controller.has_user_query:
        return
    with st.container(border=True, key="stayops_answer"):
        st.markdown('<div id="stayops-answer"></div>', unsafe_allow_html=True)
        st.markdown("### ✨ StayOps Answer")
        st.markdown(_stayops_answer(controller))


def _render_agent_activity(result: dict[str, Any]) -> None:
    _section_heading(
        "agent-activity",
        "Agent Activity",
        "How StayOps routed, analyzed, synthesized, and safety-checked this run.",
    )
    intent = result.get("intent", "operations")
    selected_specialists = result.get("selected_specialists", [])
    st.markdown(
        '<div class="agent-card">'
        '<strong>Request Router</strong>'
        f'<div class="agent-count">{escape(str(intent)).replace("_", " ").title()}</div>'
        f'<div class="muted">{len(selected_specialists)} specialists selected</div>'
        '</div><div class="flow-arrow">↓</div>',
        unsafe_allow_html=True,
    )
    runs = {run.get("agent"): run for run in result.get("agent_runs", [])}
    fields = (
        ("Booking", "booking", "booking_findings"),
        ("Guest", "guest", "guest_findings"),
        ("Turnover", "turnover", "turnover_findings"),
        ("Maintenance", "maintenance", "maintenance_findings"),
    )
    columns = st.columns(4)
    for column, (label, agent_name, field) in zip(columns, fields, strict=True):
        run = runs.get(agent_name, {})
        findings_count = len(result.get(field, []))
        if not run:
            headline = "Not needed"
            status_copy = "Not needed for this request"
        elif run.get("status") == "failed":
            headline = "Failed"
            status_copy = "Failed · Review developer details"
        else:
            headline = "Completed"
            finding_noun = "finding" if findings_count == 1 else "findings"
            seconds = float(run.get("latency_ms", 0)) / 1000
            status_copy = f"Completed · {findings_count} {finding_noun} · {seconds:.2f}s"
        with column:
            st.markdown(
                '<div class="agent-card">'
                f'<strong>{label}</strong>'
                f'<div class="agent-count">{headline}</div>'
                f'<div class="agent-status">{escape(status_copy)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    review_count = len(result.get("review_reasons", []))
    priority_count = len(result.get("priority_items", []))
    error_count = len(result.get("errors", []))
    synthesis_run = result.get("synthesis_run") or {}
    st.markdown('<div class="flow-arrow">↓</div>', unsafe_allow_html=True)
    synth_col, gate_col = st.columns(2)
    with synth_col:
        synthesis_status = str(synthesis_run.get("status", "completed")).replace(
            "_", " "
        ).title()
        synthesis_mode = str(
            synthesis_run.get("mode", "deterministic")
        ).replace("_", " ").title()
        provider = synthesis_run.get("provider")
        model = synthesis_run.get("model")
        model_copy = (
            f" · {provider}/{model}" if provider and model else ""
        )
        latency_ms = float(synthesis_run.get("latency_ms", 0))
        synthesis_copy = (
            f"{synthesis_mode}{model_copy} · {synthesis_status} · "
            f"{latency_ms:.1f}ms · {priority_count} prioritized"
        )
        st.markdown(
            '<div class="agent-card"><strong>Operations Synthesizer</strong>'
            f'<div class="agent-count">{escape(synthesis_status)}</div>'
            f'<div class="muted">{escape(synthesis_copy)}</div></div>',
            unsafe_allow_html=True,
        )
    with gate_col:
        gate_status = "Human review required" if review_count else "Checks passed"
        st.markdown(
            '<div class="agent-card"><strong>Safety Gate</strong>'
            f'<div class="agent-count">{gate_status}</div>'
            f'<div class="muted">{review_count} review reasons · {error_count} errors</div></div>',
            unsafe_allow_html=True,
        )
    with st.expander("Developer details", expanded=False):
        st.json(
            {
                "booking_findings": result.get("booking_findings", []),
                "guest_findings": result.get("guest_findings", []),
                "turnover_findings": result.get("turnover_findings", []),
                "maintenance_findings": result.get("maintenance_findings", []),
                "synthesis_run": synthesis_run,
                "agent_runs": result.get("agent_runs", []),
                "errors": result.get("errors", []),
            }
        )


def main() -> None:
    st.set_page_config(
        page_title="StayOps AI",
        page_icon="🏡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _install_theme()
    requested_view = _requested_view()
    controller = _controller()
    daily_result = controller.daily_result or {}
    summaries = build_property_summaries(daily_result)
    counts = count_property_health(summaries)

    st.markdown(
        """
        <section id="command-center" class="command-hero section-anchor">
            <h1>STAYOPS AI</h1>
            <div style="font-size:1.25rem;font-weight:760;margin:.2rem 0;">
                8 properties. One operations command center.
            </div>
            <p>Know what's ready, what's at risk, and what needs your approval.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    property_names = {summary.name: summary for summary in summaries}
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">STAYOPS AI</div>', unsafe_allow_html=True)
        _render_sidebar_navigation(requested_view)
        st.markdown("---")
        selected_name = st.selectbox(
            "Property drill-down",
            ["All properties", *property_names],
            key="property_drilldown",
        )
        activity_mode = st.toggle("Agent Activity", value=False)
        st.caption(
            f"Operating date · "
            f"{_format_date(daily_result.get('date_scope') or current_operating_date().isoformat())}"
        )
        st.markdown("---")
        st.caption("Synthetic operations data · simulated writes only")

    if requested_view == "command_center":
        st.markdown(
            '<div class="status-grid">'
            f'<div class="status-card coral"><div class="value">{counts[PropertyHealth.NEEDS_ATTENTION]}</div><div class="label">Needs Action</div></div>'
            f'<div class="status-card amber"><div class="value">{counts[PropertyHealth.WATCH]}</div><div class="label">Watch</div></div>'
            f'<div class="status-card mint"><div class="value">{counts[PropertyHealth.READY]}</div><div class="label">Ready for Guests</div></div>'
            f'<div class="status-card blue"><div class="value">{_arrivals_today(daily_result)}</div><div class="label">Arrivals Today</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    daily_warning = incomplete_analysis_message(daily_result)
    if daily_warning:
        st.error(daily_warning, icon="⚠️")

    if requested_view == "command_center":
        _render_attention(daily_result)
        _render_ask_stayops(controller)

    selected_summary = property_names.get(selected_name)
    selected_property_id = (
        selected_summary.property_id if selected_summary is not None else None
    )
    if requested_view in {"command_center", "properties"}:
        if selected_summary is None:
            _section_heading(
                "portfolio",
                "Portfolio Overview",
                "Scan readiness, arrivals, departures, and active property work.",
            )
            status_filter = st.radio(
                "Portfolio status",
                ["All", "Needs Action", "Watch", "Ready for Guests"],
                horizontal=True,
                label_visibility="collapsed",
                key="portfolio_filter",
            )
            _render_portfolio_cards(summaries, daily_result, status_filter)
        else:
            st.markdown('<div id="portfolio"></div>', unsafe_allow_html=True)
            _render_property_drilldown(daily_result, selected_summary)

    if requested_view == "command_center":
        _render_operations_views(
            daily_result,
            selected_property_id,
            requested_view,
        )
        _render_review(controller)
    elif requested_view in OPERATIONS_VIEW_TO_TAB:
        _render_operations_views(
            daily_result,
            selected_property_id,
            requested_view,
        )
    elif requested_view == "approvals":
        _render_review(controller)

    if activity_mode and controller.result is not None:
        _render_agent_activity(controller.result)


if __name__ == "__main__":
    main()
