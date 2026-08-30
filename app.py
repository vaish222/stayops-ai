"""StayOps AI operations command center."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

import streamlit as st

from src.agents.response_generator import format_stayops_response
from src.time_context import current_operating_date
from src.ui import (
    ActivityStatus,
    DashboardController,
    PropertyHealth,
    build_property_summaries,
    count_property_health,
    evidence_for_action,
    format_answer_date_context,
    format_date_context,
    format_scope_context,
    incomplete_analysis_message,
    operations_copy,
    readiness_copy,
    single_date_from_scope,
)
from src.voice import (
    ElevenLabsVoiceService,
    VoiceService,
    VoiceServiceError,
    VoiceSettings,
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
        .st-key-dashboard_date_selector {
            background:#f7fbf9; border-color:#c9ddd6; border-radius:15px;
            margin:.2rem 0 1rem; padding:.75rem .85rem;
        }
        .dashboard-date-kicker {
            color:var(--teal-dark); font-size:.67rem; font-weight:850;
            letter-spacing:.11em; text-transform:uppercase;
        }
        .dashboard-date-value { color:var(--navy); font-size:1.02rem; font-weight:820; margin-top:.12rem; }
        .metric-date-context {
            color:var(--teal-dark); font-size:.73rem; font-weight:820;
            letter-spacing:.08em; text-transform:uppercase; margin:.2rem 0 .5rem;
        }
        .answer-date-context {
            color:var(--teal-dark); font-size:.88rem; font-weight:780; margin:-.2rem 0 .75rem;
        }
        .st-key-stayops_voice {
            background:#f7fbf9; border-color:#c9ddd6; border-radius:14px;
            margin:.75rem 0;
        }
        .voice-title { color:var(--navy); font-size:.96rem; font-weight:820; }
        .voice-copy { color:var(--muted); font-size:.78rem; margin:.12rem 0 .5rem; }
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
        .approval-property-header {
            display:flex; align-items:flex-start; justify-content:space-between; gap:1rem;
            background:#e2f0eb; border:1px solid #c7ddd5; border-left:4px solid var(--teal);
            border-radius:11px; padding:.72rem .82rem; margin-bottom:.9rem;
        }
        .approval-property-name { color:var(--navy); font-size:1.16rem; font-weight:840; }
        .approval-property-context { color:var(--teal-dark); font-size:.76rem; font-weight:760; margin-top:.12rem; }
        .approval-property-count {
            color:#fff; background:var(--teal-dark); border-radius:999px;
            font-size:.72rem; font-weight:800; padding:.25rem .6rem; white-space:nowrap;
        }
        .approval-action-type { color:var(--navy); font-size:1rem; font-weight:800; margin:.1rem 0 .72rem; }
        .approval-label {
            color:var(--teal-dark); font-size:.68rem; font-weight:850;
            letter-spacing:.11em; text-transform:uppercase; margin:.62rem 0 .15rem;
        }
        .approval-copy { color:#425966; font-size:.88rem; line-height:1.5; }
        .proposal-box {
            background:#f4f8f6; border:1px solid #d5e2dc; border-radius:11px;
            color:var(--navy); font-size:.9rem; line-height:1.5; padding:.72rem .82rem;
            margin:.2rem 0 .7rem;
        }
        .status-change { display:flex; align-items:center; flex-wrap:wrap; gap:.48rem; }
        .status-change .field { color:var(--muted); font-size:.78rem; font-weight:750; margin-right:.25rem; }
        .status-change .before { color:#6f7d84; }
        .status-change .arrow { color:var(--teal-dark); font-weight:850; }
        .status-change .after { color:var(--teal-dark); font-weight:820; }
        .approval-divider { border-top:1px solid var(--line); margin:1rem 0 .85rem; }
        .st-key-stayops_answer {
            background:#edf4f9; border-color:#d8e5ee; border-radius:16px;
        }
        .asked-question {
            background:#f7fbf9; border:1px solid #c9ddd6; border-left:4px solid var(--teal);
            border-radius:11px; margin:.55rem 0 1rem; padding:.65rem .8rem;
        }
        .asked-question-label {
            color:var(--teal-dark); font-size:.66rem; font-weight:850;
            letter-spacing:.11em; text-transform:uppercase; margin-bottom:.16rem;
        }
        .asked-question-text { color:var(--navy); font-size:.92rem; font-weight:680; }
        .agent-card { min-height:112px; }
        .agent-card strong { color:var(--navy); }
        .agent-count { font-size:1.12rem; font-weight:800; color:var(--teal-dark); margin:.35rem 0 .2rem; }
        .agent-status { color:#526570; font-size:.8rem; line-height:1.35; }
        .flow-arrow { text-align:center; color:#789098; font-size:1.25rem; line-height:1; padding:.15rem; }
        .st-key-agent_activity_panel {
            position: sticky;
            top: 1rem;
            max-height: calc(100vh - 2rem);
            overflow-y: auto;
            background: #f4f8f6;
            border: 1px solid #d3e0da;
            border-radius: 17px;
            padding: .9rem .85rem;
        }
        .activity-header { margin-bottom:.7rem; }
        .activity-title { color:var(--navy); font-size:1rem; font-weight:820; }
        .activity-copy { color:var(--muted); font-size:.72rem; line-height:1.35; margin-top:.16rem; }
        .activity-ready {
            background:var(--card); border:1px dashed #b9cec5; border-radius:12px;
            color:#526570; font-size:.78rem; line-height:1.45; padding:.75rem;
        }
        .activity-row { display:grid; grid-template-columns:16px 1fr; gap:.48rem; position:relative; padding:0 0 .72rem; }
        .activity-row:not(:last-child)::after {
            content:""; position:absolute; left:6px; top:15px; bottom:0; width:1px; background:#cbd8d2;
        }
        .activity-dot { width:13px; height:13px; border-radius:50%; margin-top:.15rem; background:#aab6b2; border:2px solid #f4f8f6; z-index:1; }
        .activity-dot.running { background:#16877e; animation:activity-pulse 1.2s ease-in-out infinite; }
        .activity-dot.completed { background:#4f9a75; }
        .activity-dot.not_needed, .activity-dot.queued { background:#aeb9b5; }
        .activity-dot.waiting_approval { background:#d39a2f; }
        .activity-dot.failed, .activity-dot.rejected { background:#ce6257; }
        .activity-dot.fallback { background:#b4842e; }
        .activity-label { color:var(--navy); font-size:.78rem; font-weight:760; line-height:1.2; }
        .activity-detail { color:#61727a; font-size:.68rem; line-height:1.35; margin-top:.1rem; }
        .activity-status { font-weight:750; }
        @keyframes activity-pulse { 50% { opacity:.35; transform:scale(.82); } }
        .sidebar-brand { font-size:1.1rem; font-weight:850; color:var(--navy); letter-spacing:.08em; margin:.15rem 0 1rem; }
        .st-key-home_button button {
            width:100%; justify-content:flex-start; background:#f7fbf9;
            border:1px solid #bdd3ca; color:var(--teal-dark); font-weight:760;
        }
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
            .st-key-agent_activity_panel { position:static; max-height:none; overflow:visible; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _today_for(controller: DashboardController) -> date:
    return controller.reference_date or current_operating_date()


def _dashboard_date(controller: DashboardController) -> date:
    if "dashboard_date" not in st.session_state:
        st.session_state.dashboard_date = _today_for(controller)
    selected = st.session_state.dashboard_date
    if isinstance(selected, datetime):
        selected = selected.date()
        st.session_state.dashboard_date = selected
    return selected


def _controller() -> DashboardController:
    if "stayops_controller" not in st.session_state:
        st.session_state.stayops_controller = DashboardController()
    controller: DashboardController = st.session_state.stayops_controller
    dashboard_date = _dashboard_date(controller)
    if controller.daily_briefing_needs_refresh_for(dashboard_date):
        controller.load_daily_briefing(dashboard_date)
    return controller


def _configured_voice_service() -> tuple[VoiceService | None, str | None]:
    """Build the optional voice boundary without affecting graph startup."""

    existing = st.session_state.get("stayops_voice_service")
    if existing is not None:
        return existing, None
    try:
        settings = VoiceSettings.from_environment()
        if not settings.enabled:
            return None, None
        service = ElevenLabsVoiceService(settings)
    except (ValueError, VoiceServiceError) as exc:
        return None, str(exc)
    except Exception:
        return None, "ElevenLabs voice configuration could not be initialized."
    st.session_state.stayops_voice_service = service
    return service, None


def _set_dashboard_date(value: date) -> None:
    st.session_state.dashboard_date = value


def _shift_dashboard_date(days: int) -> None:
    selected = st.session_state.get("dashboard_date", current_operating_date())
    if isinstance(selected, datetime):
        selected = selected.date()
    st.session_state.dashboard_date = selected + timedelta(days=days)


def _render_dashboard_date_selector(
    dashboard_date: date,
    today: date,
) -> None:
    with st.container(border=True, key="dashboard_date_selector"):
        label_column, previous_column, today_column, next_column, picker_column = (
            st.columns([2.25, .72, .72, .72, 1.25], vertical_alignment="center")
        )
        label_column.markdown(
            '<div class="dashboard-date-kicker">Viewing operations for</div>'
            '<div class="dashboard-date-value">'
            f'{escape(format_date_context(dashboard_date, today))}</div>',
            unsafe_allow_html=True,
        )
        previous_column.button(
            "Previous",
            key="dashboard_date_previous",
            on_click=_shift_dashboard_date,
            args=(-1,),
            width="stretch",
        )
        today_column.button(
            "Today",
            key="dashboard_date_today",
            on_click=_set_dashboard_date,
            args=(today,),
            width="stretch",
        )
        next_column.button(
            "Next",
            key="dashboard_date_next",
            on_click=_shift_dashboard_date,
            args=(1,),
            width="stretch",
        )
        picker_column.date_input(
            "Choose date",
            key="dashboard_date",
            label_visibility="collapsed",
        )


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
        if selected_view in OPERATIONS_VIEW_TO_TAB:
            st.session_state.operations_tab = OPERATIONS_VIEW_TO_TAB[selected_view]
        st.query_params["view"] = selected_view


def _go_home() -> None:
    """Reset all navigation state and return to the Command Center."""

    st.query_params["view"] = "command_center"
    st.session_state.sidebar_navigation = "Command Center"
    st.session_state.property_drilldown = "All properties"


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
                    f"{record['guest_name']}: check-in "
                    f"{_format_date(record['check_in_date'])} at "
                    f"{_format_time(record.get('check_in_time'))}; check-out "
                    f"{_format_date(record['check_out_date'])} at "
                    f"{_format_time(record.get('check_out_time'))}."
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


def _run_query(
    controller: DashboardController,
    query: str,
    activity_slot: Any | None = None,
) -> None:
    def refresh_activity() -> None:
        if activity_slot is not None:
            _render_agent_activity(controller, activity_slot)

    try:
        controller.run_query(query, on_activity=refresh_activity)
    except ValueError as exc:
        st.session_state.stayops_notice = ("warning", str(exc))
    else:
        st.session_state.pop("stayops_notice", None)


def _resume_review(
    controller: DashboardController,
    decision: str,
    action_id: str | None,
    edited_description: str | None = None,
    activity_slot: Any | None = None,
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
        def refresh_activity() -> None:
            if activity_slot is not None:
                _render_agent_activity(controller, activity_slot)

        result = controller.resume_review(
            decision,
            action_id=action_id,
            edited_description=edited_description,
            on_activity=refresh_activity,
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


def _render_attention(
    result: dict[str, Any],
    dashboard_date: date,
    today: date,
) -> None:
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
        f"Needs Your Attention — {format_date_context(dashboard_date, today)}",
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


def _clear_voice_transcript() -> None:
    """Discard transcript state when the microphone recording changes."""

    st.session_state.pop("stayops_voice_transcript", None)
    st.session_state.pop("stayops_voice_transcript_editor", None)


def _render_voice_question(
    controller: DashboardController,
    voice_service: VoiceService,
    activity_slot: Any | None,
) -> None:
    """Capture and confirm a transcript before using the normal query path."""

    with st.container(border=True, key="stayops_voice"):
        st.markdown(
            '<div class="voice-title">🎙 Ask by voice</div>'
            '<div class="voice-copy">Record a question, review the transcript, '
            'then send it through the same StayOps safety workflow.</div>',
            unsafe_allow_html=True,
        )
        recording = st.audio_input(
            "Record an Ask StayOps question",
            sample_rate=16_000,
            key="stayops_voice_recording",
            on_change=_clear_voice_transcript,
        )
        if recording is not None and st.button(
            "Transcribe recording",
            key="transcribe_voice_question",
        ):
            try:
                with st.spinner("Transcribing your question with ElevenLabs…"):
                    transcription = voice_service.transcribe(
                        recording.getvalue()
                    )
            except VoiceServiceError as exc:
                st.session_state.stayops_notice = ("error", str(exc))
            else:
                st.session_state.stayops_voice_transcript = transcription.text
                st.session_state.stayops_voice_transcript_editor = (
                    transcription.text
                )
                st.session_state.pop("stayops_notice", None)

        transcript = st.session_state.get("stayops_voice_transcript")
        if transcript:
            with st.form("confirm_voice_question"):
                confirmed_transcript = st.text_input(
                    "I heard",
                    key="stayops_voice_transcript_editor",
                    help="Edit any transcription errors before asking StayOps.",
                )
                submitted = st.form_submit_button(
                    "Ask StayOps with voice",
                    type="primary",
                )
            if submitted:
                _run_query(
                    controller,
                    confirmed_transcript,
                    activity_slot,
                )
        st.caption(
            "Voice can ask operational questions, but approvals remain on-screen only."
        )


def _spoken_answer_text(answer: str) -> str:
    """Remove Markdown punctuation that should not be read aloud."""

    spoken = re.sub(r"(?m)^#{1,6}\s*", "", answer)
    spoken = re.sub(r"(?m)^\s*[-*]\s+", "", spoken)
    spoken = spoken.replace("**", "").replace("`", "")
    return re.sub(r"\n{2,}", "\n", spoken).strip()


def _render_spoken_answer(
    voice_service: VoiceService | None,
    answer: str,
) -> None:
    """Generate TTS only on demand and cache only the latest answer audio."""

    if voice_service is None or not voice_service.can_synthesize:
        return
    digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    cached = st.session_state.get("stayops_voice_answer_cache", {})
    audio = cached.get(digest)
    if audio is None and st.button(
        "🔊 Play answer",
        key=f"play_stayops_answer_{digest[:12]}",
    ):
        try:
            with st.spinner("Preparing the spoken StayOps answer…"):
                audio = voice_service.synthesize(
                    _spoken_answer_text(answer)
                )
        except VoiceServiceError as exc:
            st.error(str(exc))
        else:
            st.session_state.stayops_voice_answer_cache = {digest: audio}
    if audio is not None:
        st.audio(audio, format=voice_service.output_mime_type)


def _render_ask_stayops(
    controller: DashboardController,
    dashboard_date: date,
    today: date,
    activity_slot: Any | None = None,
) -> None:
    voice_service, voice_error = _configured_voice_service()
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
        _run_query(controller, query, activity_slot)

    if voice_service is not None:
        _render_voice_question(controller, voice_service, activity_slot)
    elif voice_error is not None:
        st.warning(f"Voice input is unavailable: {voice_error}")

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
            _run_query(controller, prompt, activity_slot)
    _show_notice()
    _render_stayops_answer(
        controller,
        dashboard_date,
        today,
        voice_service,
    )


def _property_card_details(
    result: dict[str, Any],
    property_id: str,
    today: date,
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
    operating_date = single_date_from_scope(result.get("date_scope"))
    date_label = (
        format_date_context(operating_date, today)
        if operating_date is not None
        else "Selected date"
    )
    next_arrival = (
        f"{date_label}, {_format_time(arrivals[0].get('check_in_time'))}"
        if arrivals
        else f"No arrival · {date_label}"
    )
    next_departure = (
        f"{date_label}, {_format_time(departures[0].get('check_out_time'))}"
        if departures
        else f"No departure · {date_label}"
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
    today: date,
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
            result,
            summary.property_id,
            today,
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
                    '<div class="detail-line">'
                    f'{escape(_humanize_embedded_dates(summary.headline))}</div>'
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
                    '<div class="issue-title">'
                    f'{escape(_humanize_embedded_dates(finding["summary"]))}</div>',
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
    dashboard_date: date,
    today: date,
) -> None:
    _section_heading(
        "operations-workspace",
        "Operations Workspace",
        f"{format_date_context(dashboard_date, today)} · "
        f"{operations_copy(dashboard_date, today)}",
    )
    tab_labels = list(OPERATIONS_VIEW_TO_TAB.values())
    requested_tab = OPERATIONS_VIEW_TO_TAB.get(
        requested_view,
        "Needs Your Attention",
    )
    previous_route = st.session_state.get("operations_requested_view")
    if (
        "operations_tab" not in st.session_state
        or previous_route != requested_view
    ):
        st.session_state.operations_tab = requested_tab
    st.session_state.operations_requested_view = requested_view
    priorities, messages, cleanings, maintenance, arrivals = st.tabs(
        tab_labels,
        key="operations_tab",
        on_change="rerun",
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
        return (
            "Approval is required because this action sends a message to the guest."
        )
    if tool_name == "send_cleaner_message":
        return (
            "Approval is required because this action sends a message to the cleaner."
        )
    if tool_name == "update_maintenance_status":
        return (
            "Approval is required because this action changes an operational record."
        )
    return (
        "Approval is required before StayOps can continue with this operational step."
    )


def _approval_action_label(action: dict[str, Any]) -> str:
    labels = {
        "send_guest_message": "Reply to guest",
        "send_cleaner_message": "Contact cleaner",
        "update_maintenance_status": "Update maintenance status",
    }
    return labels.get(
        action.get("tool_name"),
        _humanize(action.get("action_type", "Review action")),
    )


def _findings_for_action(
    action: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = set(action.get("source_finding_ids", []))
    return [
        finding
        for finding in findings
        if source_ids.intersection(finding.get("source_finding_ids", []))
    ]


def _humanize_embedded_dates(value: str) -> str:
    """Make ISO dates readable while preserving the graph-provided wording."""

    return re.sub(
        r"\b\d{4}-\d{2}-\d{2}\b",
        lambda match: _format_date(match.group()),
        value,
    )


def _approval_why_now(
    action: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    supporting = _findings_for_action(action, findings)
    summary = next(
        (
            str(finding.get("summary", "")).strip()
            for finding in supporting
            if str(finding.get("summary", "")).strip()
        ),
        str(action.get("description", "Review this operational action.")).strip(),
    )
    return _humanize_embedded_dates(summary)


def _group_approval_actions(
    actions: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group actions by property while retaining their priority order."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        grouped.setdefault(action["property_id"], []).append(action)
    return list(grouped.items())


def _approval_proposal_markup(
    action: dict[str, Any],
    result: dict[str, Any],
) -> str:
    tool_name = action.get("tool_name")
    if tool_name in {"send_guest_message", "send_cleaner_message"}:
        message = action.get("parameters", {}).get("message") or action.get(
            "description",
            "",
        )
        return (
            '<div class="approval-label">Proposed message</div>'
            f'<div class="proposal-box">“{escape(str(message))}”</div>'
        )
    if tool_name == "update_maintenance_status":
        target_record_id = action.get("target_record_id")
        record = result.get("maintenance_context", {}).get(target_record_id, {})
        current_value = record.get("status")
        proposed_value = action.get("parameters", {}).get("status")
        current_status = (
            _humanize(current_value) if current_value else "Not available"
        )
        proposed_status = (
            _humanize(proposed_value) if proposed_value else "Not provided"
        )
        return (
            '<div class="approval-label">Proposed change</div>'
            '<div class="proposal-box status-change">'
            '<span class="field">Maintenance status</span>'
            f'<span class="before">{escape(current_status)}</span>'
            '<span class="arrow">→</span>'
            f'<span class="after">{escape(proposed_status)}</span>'
            '</div>'
        )
    return (
        '<div class="approval-label">Proposed action</div>'
        '<div class="proposal-box">'
        f'{escape(str(action.get("description", "")))}</div>'
    )


def _render_approval_action(
    controller: DashboardController,
    action: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
    activity_slot: Any | None,
) -> None:
    action_id = action["action_id"]
    tool_name = action.get("tool_name")
    approve_label = (
        "Approve & Send"
        if tool_name in {"send_guest_message", "send_cleaner_message"}
        else "Approve & Update"
        if tool_name == "update_maintenance_status"
        else "Approve"
    )
    st.markdown(
        '<div class="approval-action-type">'
        f'{escape(_approval_action_label(action))}</div>'
        '<div class="approval-label">Why now</div>'
        '<div class="approval-copy">'
        f'{escape(_approval_why_now(action, request.get("findings", [])))}</div>'
        '<div class="approval-label">Approval required</div>'
        f'<div class="approval-copy">{escape(_approval_explanation(action))}</div>'
        f'{_approval_proposal_markup(action, result)}',
        unsafe_allow_html=True,
    )
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
            _resume_review(
                controller,
                "approve",
                action_id,
                activity_slot=activity_slot,
            )
        st.rerun()
    if reject_col.button(
        "Reject",
        width="stretch",
        key=f"reject_{controller.thread_id}_{action_id}",
    ):
        _resume_review(
            controller,
            "reject",
            action_id,
            activity_slot=activity_slot,
        )
        st.rerun()
    supporting = evidence_for_action(action, request.get("findings", []))
    plain_evidence = _plain_evidence_lines(supporting, result)
    with st.expander("View source details"):
        for line in plain_evidence:
            st.write(line)


def _render_review(
    controller: DashboardController,
    activity_slot: Any | None = None,
) -> None:
    request = controller.pending_review
    _section_heading(
        "approval-center",
        "Human Approvals",
        "Review each action StayOps cannot take without you.",
    )
    if request is None:
        st.info("No approvals are pending for the latest StayOps request.")
        return
    result = controller.result or controller.daily_result or {}
    actions = request.get("proposed_actions", [])
    if not actions:
        st.error("StayOps could not complete this operational check.")
        st.write("Please acknowledge the incomplete analysis before continuing.")
        if st.button(
            "Acknowledge",
            type="primary",
            key=f"acknowledge_{controller.thread_id}",
        ):
            _resume_review(controller, "approve", None, activity_slot=activity_slot)
            st.rerun()
        return
    st.markdown(
        '<div class="approval-banner">'
        '<strong>Your approval is needed</strong>'
        '<span>StayOps found actions it cannot take without you.<br>'
        'Nothing is sent or changed until you approve.</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Simulation mode: no external message is sent. Approved changes are saved "
        "to the local demo runtime and reflected in these screens."
    )
    approval_date = format_scope_context(
        result.get("date_scope"),
        _today_for(controller),
    )
    for property_id, property_actions in _group_approval_actions(actions):
        property_name = _property_name(result, property_id)
        action_count = len(property_actions)
        count_label = (
            "1 action needs your approval"
            if action_count == 1
            else f"{action_count} actions need your approval"
        )
        with st.container(border=True):
            date_markup = (
                '<div class="approval-property-context">'
                f'{escape(approval_date)}</div>'
                if result.get("date_scope")
                else ""
            )
            st.markdown(
                '<div class="approval-property-header">'
                '<div>'
                f'<div class="approval-property-name">{escape(property_name)}</div>'
                f'{date_markup}</div>'
                f'<div class="approval-property-count">{escape(count_label)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            for index, action in enumerate(property_actions):
                if index:
                    st.markdown(
                        '<div class="approval-divider"></div>',
                        unsafe_allow_html=True,
                    )
                _render_approval_action(
                    controller,
                    action,
                    request,
                    result,
                    activity_slot,
                )


def _stayops_answer(controller: DashboardController) -> str:
    result = controller.result
    if result is None:
        return "StayOps has not run yet."
    return format_stayops_response(result)


def _render_stayops_answer(
    controller: DashboardController,
    dashboard_date: date,
    today: date,
    voice_service: VoiceService | None = None,
) -> None:
    if not controller.has_user_query:
        return
    result = controller.result or {}
    query_scope = result.get("date_scope")
    query_date = single_date_from_scope(query_scope)
    with st.container(border=True, key="stayops_answer"):
        st.markdown('<div id="stayops-answer"></div>', unsafe_allow_html=True)
        st.markdown("### ✨ StayOps Answer")
        if controller.last_query:
            st.markdown(
                '<div class="asked-question">'
                '<div class="asked-question-label">You asked</div>'
                '<div class="asked-question-text">'
                f'“{escape(controller.last_query)}”</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div class="answer-date-context">'
            f'{escape(format_answer_date_context(query_scope, today))}</div>',
            unsafe_allow_html=True,
        )
        answer = _stayops_answer(controller)
        st.markdown(answer)
        _render_spoken_answer(voice_service, answer)
        if query_date is not None and query_date != dashboard_date:
            st.button(
                f"View {format_date_context(query_date, today)} operations →",
                key="switch_to_query_date",
                type="primary",
                on_click=_set_dashboard_date,
                args=(query_date,),
            )


def _render_agent_activity(
    controller: DashboardController,
    activity_slot: Any,
) -> None:
    """Refresh the compact, sticky execution timeline in one placeholder."""

    status_copy = {
        ActivityStatus.QUEUED: "Queued",
        ActivityStatus.RUNNING: "Running",
        ActivityStatus.COMPLETED: "Completed",
        ActivityStatus.NOT_NEEDED: "Not needed",
        ActivityStatus.WAITING_APPROVAL: "Waiting",
        ActivityStatus.FAILED: "Failed",
        ActivityStatus.FALLBACK: "Fallback",
        ActivityStatus.REJECTED: "Rejected",
    }
    with activity_slot.container():
        st.markdown(
            '<div id="agent-activity" class="activity-header">'
            '<div class="activity-title">Agent Activity</div>'
            '<div class="activity-copy">Live progress for your latest request.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        if not controller.activity_steps:
            st.markdown(
                '<div class="activity-ready"><strong>Ready for your question</strong><br>'
                'Ask StayOps to watch routing, specialist analysis, safety checks, '
                'and approvals as they happen.</div>',
                unsafe_allow_html=True,
            )
            return

        rows = []
        for step in controller.activity_steps.values():
            status = status_copy[step.status]
            rows.append(
                '<div class="activity-row">'
                f'<div class="activity-dot {step.status.value}"></div>'
                '<div>'
                f'<div class="activity-label">{escape(step.label)}</div>'
                f'<div class="activity-detail"><span class="activity-status">'
                f'{escape(status)}</span> · {escape(step.detail)}</div>'
                '</div></div>'
            )
        st.markdown("".join(rows), unsafe_allow_html=True)

        result = controller.result
        if result is not None and not controller.activity_running:
            with st.expander("Developer details", expanded=False):
                st.json(
                    {
                        "booking_findings": result.get("booking_findings", []),
                        "guest_findings": result.get("guest_findings", []),
                        "turnover_findings": result.get("turnover_findings", []),
                        "maintenance_findings": result.get(
                            "maintenance_findings",
                            [],
                        ),
                        "synthesis_run": result.get("synthesis_run") or {},
                        "agent_runs": result.get("agent_runs", []),
                        "errors": result.get("errors", []),
                    }
                )


def _render_dashboard_content(
    *,
    controller: DashboardController,
    requested_view: str,
    daily_result: dict[str, Any],
    summaries: list[Any],
    counts: dict[PropertyHealth, int],
    property_names: dict[str, Any],
    selected_name: str,
    dashboard_date: date,
    today: date,
    activity_slot: Any,
) -> None:
    """Render the selected workspace beside the persistent activity rail."""

    _render_dashboard_date_selector(dashboard_date, today)

    if requested_view == "command_center":
        arrivals_label = (
            "Arrivals Today"
            if dashboard_date == today
            else "Arrivals Tomorrow"
            if dashboard_date == today + timedelta(days=1)
            else "Arrivals Yesterday"
            if dashboard_date == today - timedelta(days=1)
            else "Arrivals"
        )
        st.markdown(
            '<div class="metric-date-context">Operations snapshot · '
            f'{escape(format_date_context(dashboard_date, today))}</div>'
            '<div class="status-grid">'
            f'<div class="status-card coral"><div class="value">{counts[PropertyHealth.NEEDS_ATTENTION]}</div><div class="label">Needs Action</div></div>'
            f'<div class="status-card amber"><div class="value">{counts[PropertyHealth.WATCH]}</div><div class="label">Watch</div></div>'
            f'<div class="status-card mint"><div class="value">{counts[PropertyHealth.READY]}</div><div class="label">Ready for Guests</div></div>'
            f'<div class="status-card blue"><div class="value">{_arrivals_today(daily_result)}</div><div class="label">{escape(arrivals_label)}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    daily_warning = incomplete_analysis_message(daily_result)
    if daily_warning:
        st.error(daily_warning, icon="⚠️")

    if requested_view == "command_center":
        _render_attention(daily_result, dashboard_date, today)
        _render_ask_stayops(
            controller,
            dashboard_date,
            today,
            activity_slot,
        )

    selected_summary = property_names.get(selected_name)
    selected_property_id = (
        selected_summary.property_id if selected_summary is not None else None
    )
    if requested_view in {"command_center", "properties"}:
        if selected_summary is None:
            _section_heading(
                "portfolio",
                f"Portfolio Overview — {format_date_context(dashboard_date, today)}",
                readiness_copy(dashboard_date, today, len(summaries)),
            )
            status_filter = st.radio(
                "Portfolio status",
                ["All", "Needs Action", "Watch", "Ready for Guests"],
                horizontal=True,
                label_visibility="collapsed",
                key="portfolio_filter",
            )
            _render_portfolio_cards(
                summaries,
                daily_result,
                status_filter,
                today,
            )
        else:
            st.markdown('<div id="portfolio"></div>', unsafe_allow_html=True)
            _render_property_drilldown(daily_result, selected_summary)

    if requested_view == "command_center":
        _render_operations_views(
            daily_result,
            selected_property_id,
            requested_view,
            dashboard_date,
            today,
        )
        _render_review(controller, activity_slot)
    elif requested_view in OPERATIONS_VIEW_TO_TAB:
        _render_operations_views(
            daily_result,
            selected_property_id,
            requested_view,
            dashboard_date,
            today,
        )
    elif requested_view == "approvals":
        _render_review(controller, activity_slot)


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
    today = _today_for(controller)
    dashboard_date = _dashboard_date(controller)
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
        st.button(
            "⌂  Home",
            key="home_button",
            on_click=_go_home,
            width="stretch",
        )
        _render_sidebar_navigation(requested_view)
        st.markdown("---")
        selected_name = st.selectbox(
            "Property drill-down",
            ["All properties", *property_names],
            key="property_drilldown",
        )
        st.caption(
            f"Operating date · {format_date_context(dashboard_date, today)}"
        )
        st.markdown("---")
        st.caption("Synthetic operations data · simulated writes only")

    content_column, activity_column = st.columns([3.15, 1], gap="large")
    with activity_column:
        with st.container(key="agent_activity_panel"):
            activity_slot = st.empty()
            _render_agent_activity(controller, activity_slot)
    with content_column:
        _render_dashboard_content(
            controller=controller,
            requested_view=requested_view,
            daily_result=daily_result,
            summaries=summaries,
            counts=counts,
            property_names=property_names,
            selected_name=selected_name,
            dashboard_date=dashboard_date,
            today=today,
            activity_slot=activity_slot,
        )


if __name__ == "__main__":
    main()
