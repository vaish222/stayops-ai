"""StayOps AI Phase 9 Streamlit dashboard."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

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
    PropertyHealth.NEEDS_ATTENTION: "Needs attention",
    PropertyHealth.WATCH: "Watch",
    PropertyHealth.READY: "Ready",
}
STATUS_ICONS = {
    PropertyHealth.NEEDS_ATTENTION: "●",
    PropertyHealth.WATCH: "◆",
    PropertyHealth.READY: "✓",
}


def _install_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #172b32;
            --muted: #62747a;
            --paper: #f7f5ef;
            --card: #fffdfa;
            --teal: #0f6d68;
            --teal-dark: #094b49;
            --amber: #d8912f;
            --coral: #c85447;
            --line: #dfe4df;
        }
        .stApp { background: var(--paper); color: var(--ink); }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stSidebar"] {
            background: #eaf0ec;
            border-right: 1px solid #d3ddd7;
        }
        .block-container { max-width: 1240px; padding-top: 2rem; }
        .hero {
            padding: 1.7rem 1.9rem;
            border-radius: 22px;
            color: white;
            background: linear-gradient(125deg, #0a4e4c 0%, #11766f 60%, #289188 100%);
            box-shadow: 0 16px 40px rgba(20, 73, 70, 0.16);
            margin-bottom: 1.2rem;
        }
        .eyebrow {
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .16em;
            text-transform: uppercase;
            opacity: .78;
        }
        .hero h1 { font-size: 2.35rem; margin: .25rem 0 .15rem; }
        .hero p { margin: 0; font-size: 1.02rem; opacity: .86; }
        [data-testid="stMetric"] {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 16px;
            padding: .85rem 1rem;
            box-shadow: 0 7px 22px rgba(38, 61, 57, .05);
        }
        [data-testid="stMetricValue"] { color: var(--ink); font-weight: 750; }
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
        .needs_attention { color: #8f3129; background: #f9ddd8; }
        .watch { color: #87570d; background: #f8e8c9; }
        .ready { color: #176058; background: #d9efea; }
        .issue-title { font-size: 1.04rem; font-weight: 750; margin: .45rem 0 .2rem; }
        .muted { color: var(--muted); font-size: .88rem; }
        .property-name { font-weight: 750; font-size: 1rem; }
        div.stButton > button[kind="primary"] {
            background: var(--teal); border-color: var(--teal); font-weight: 700;
        }
        div.stButton > button { border-radius: 10px; font-weight: 650; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _controller() -> DashboardController:
    if "stayops_controller" not in st.session_state:
        st.session_state.stayops_controller = DashboardController()
    controller: DashboardController = st.session_state.stayops_controller
    if controller.daily_result is None:
        controller.load_daily_briefing()
    return controller


def _status_pill(health: PropertyHealth) -> str:
    return (
        f'<span class="status-pill {health.value}">'
        f"{STATUS_ICONS[health]} {STATUS_LABELS[health]}</span>"
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
        st.session_state.stayops_notice = (
            "info",
            "StayOps analyzed the request using the existing operations graph.",
        )


def _resume_review(
    controller: DashboardController,
    decision: str,
    action_id: str | None,
    edited_description: str | None = None,
) -> None:
    review = controller.pending_review or {}
    acknowledgement_only = not review.get("proposed_actions")
    try:
        result = controller.resume_review(
            decision,
            action_id=action_id,
            edited_description=edited_description,
        )
    except (RuntimeError, ValueError) as exc:
        st.session_state.stayops_notice = ("error", str(exc))
        return
    if controller.pending_review is not None:
        st.session_state.stayops_notice = (
            "warning",
            "The edited action is ready for reconfirmation.",
        )
    elif decision == "approve":
        execution_count = len(result.get("executed_actions", []))
        st.session_state.stayops_notice = (
            "success",
            (
                "Incomplete analysis acknowledged. No simulated action was executed."
                if acknowledgement_only and execution_count == 0
                else
                f"Approved. {execution_count} simulated action executed."
                if execution_count == 1
                else f"Approved. {execution_count} simulated actions executed."
            ),
        )
    else:
        st.session_state.stayops_notice = (
            "info",
            "Rejected. No action was executed.",
        )


def _render_portfolio_cards(summaries) -> None:
    st.subheader("Portfolio at a glance")
    columns = st.columns(2)
    for index, summary in enumerate(summaries):
        with columns[index % 2]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="property-name">{escape(summary.name)}</div>'
                    f'<div class="muted">{escape(summary.location)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(_status_pill(summary.health), unsafe_allow_html=True)
                st.write(summary.headline)


def _render_property_drilldown(
    result: dict[str, Any],
    summary,
) -> None:
    record = result["property_context"][summary.property_id]
    st.subheader(summary.name)
    st.markdown(_status_pill(summary.health), unsafe_allow_html=True)
    st.caption(summary.location)

    overview_tab, stays_tab, operations_tab = st.tabs(
        ["Overview", "Stays", "Operations"]
    )
    with overview_tab:
        c1, c2, c3 = st.columns(3)
        c1.metric("Bedrooms", record["bedrooms"])
        c2.metric("Bathrooms", record["bathrooms"])
        c3.metric("Max guests", record["max_guests"])
        st.write(record["description"])

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
                        "Check-in": item["check_in_date"],
                        "Check-out": item["check_out_date"],
                        "Status": item["status"],
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
                    f"{item['scheduled_date']} · {item['cleaner_name']} · "
                    f"{item['confirmation_status']}"
                )
        else:
            st.caption("No cleaning jobs in scope.")
        st.markdown("**Maintenance**")
        if maintenance:
            for item in maintenance:
                st.write(
                    f"{item['summary']} · {item['severity']} · {item['status']}"
                )
        else:
            st.caption("No maintenance tickets in scope.")


def _render_priorities(
    result: dict[str, Any],
    property_id: str | None,
) -> None:
    st.subheader("Prioritized issues")
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
            with st.expander("Evidence"):
                for item in finding.get("evidence", []):
                    st.markdown(
                        f"**{item['source'].replace('_', ' ').title()}** · "
                        f"`{', '.join(item['record_ids'])}`"
                    )
                    st.write(item["fact"])


def _render_review(controller: DashboardController) -> None:
    request = controller.pending_review
    if request is None:
        return
    st.markdown("---")
    st.subheader("Human approval required")
    st.warning(request["question"])
    for reason in request.get("review_reasons", []):
        st.error(reason["message"], icon="⚠️")
    actions = request.get("proposed_actions", [])
    action_by_id = {action["action_id"]: action for action in actions}
    action_ids = list(action_by_id)
    selected_id = st.selectbox(
        "Proposed action",
        options=action_ids or [None],
        format_func=lambda action_id: (
            action_by_id[action_id]["description"] if action_id else "Review only"
        ),
        key=f"review_action_{controller.thread_id}",
    )
    selected = action_by_id.get(selected_id) if selected_id else None
    if selected is not None:
        with st.container(border=True):
            st.markdown(f"**{selected['description']}**")
            tool_label = selected.get("tool_name") or "No write tool"
            st.caption(
                f"{tool_label} · {selected.get('target_record_id') or 'review only'}"
            )
            supporting = evidence_for_action(selected, request.get("findings", []))
            with st.expander("Review supporting evidence", expanded=True):
                for item in supporting:
                    st.write(item["fact"])
                    st.caption(
                        f"{item['source']} · {', '.join(item['record_ids'])}"
                    )

    edit_key = f"edited_action_{controller.thread_id}_{selected_id}"
    edited_description = st.text_area(
        "Edit action before reconfirming",
        value=selected["description"] if selected else "",
        disabled=selected is None,
        key=edit_key,
    )
    approve_col, edit_col, reject_col = st.columns(3)
    if approve_col.button(
        "Acknowledge" if not actions else "Approve",
        type="primary",
        width="stretch",
        key=f"approve_{controller.thread_id}",
    ):
        _resume_review(controller, "approve", selected_id)
        st.rerun()
    if edit_col.button(
        "Edit & reconfirm",
        width="stretch",
        disabled=selected is None or not edited_description.strip(),
        key=f"edit_{controller.thread_id}",
    ):
        _resume_review(
            controller,
            "edit",
            selected_id,
            edited_description.strip(),
        )
        st.rerun()
    if reject_col.button(
        "Reject",
        width="stretch",
        key=f"reject_{controller.thread_id}",
    ):
        _resume_review(controller, "reject", selected_id)
        st.rerun()


def _render_latest_result(controller: DashboardController) -> None:
    result = controller.result
    if result is None:
        return
    st.subheader("Latest StayOps response")
    st.caption(controller.last_query)
    warning = (
        incomplete_analysis_message(result)
        if result is not controller.daily_result
        else None
    )
    if warning:
        st.error(warning, icon="⚠️")
    st.write(result.get("final_response") or "The workflow returned no narrative response.")
    if result.get("executed_actions"):
        for execution in result["executed_actions"]:
            st.success(
                f"Simulated: {execution['tool_name']} → "
                f"{execution['target_record_id']}"
            )
    if result.get("errors"):
        st.error(f"{len(result['errors'])} workflow error(s) were recorded.")


def _render_debug(result: dict[str, Any]) -> None:
    st.markdown("---")
    st.subheader("Specialist findings · debug")
    for label, field in (
        ("Booking", "booking_findings"),
        ("Guest", "guest_findings"),
        ("Turnover", "turnover_findings"),
        ("Maintenance", "maintenance_findings"),
    ):
        with st.expander(f"{label} · {len(result.get(field, []))} findings"):
            st.json(result.get(field, []))
    with st.expander("Agent runs and workflow errors"):
        st.json(
            {
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
    controller = _controller()
    daily_result = controller.daily_result or {}
    summaries = build_property_summaries(daily_result)
    counts = count_property_health(summaries)

    st.markdown(
        """
        <section class="hero">
            <div class="eyebrow">Daily operations briefing</div>
            <h1>STAYOPS AI</h1>
            <p>Your 8 properties. One clear view.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(3)
    metric_columns[0].metric(
        "Need attention", counts[PropertyHealth.NEEDS_ATTENTION]
    )
    metric_columns[1].metric("Watch", counts[PropertyHealth.WATCH])
    metric_columns[2].metric("Ready", counts[PropertyHealth.READY])

    daily_warning = incomplete_analysis_message(daily_result)
    if daily_warning:
        st.error(daily_warning, icon="⚠️")

    with st.sidebar:
        st.markdown("### Portfolio view")
        property_names = {summary.name: summary for summary in summaries}
        selected_name = st.selectbox(
            "Property drill-down",
            ["All properties", *property_names],
            key="property_drilldown",
        )
        debug_mode = st.toggle("Debug specialist findings", value=False)
        st.caption(f"Operating date · {daily_result.get('date_scope', '2026-08-28')}")
        st.markdown("---")
        st.caption("Synthetic operations data · simulated writes only")

    st.markdown("### Ask StayOps")
    with st.form("ask_stayops", clear_on_submit=True):
        query = st.text_input(
            "Operational question",
            placeholder="What needs my attention today?",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Analyze", type="primary")
    if submitted:
        _run_query(controller, query)
    _show_notice()

    selected_summary = property_names.get(selected_name)
    if selected_summary is None:
        _render_portfolio_cards(summaries)
        selected_property_id = None
    else:
        _render_property_drilldown(daily_result, selected_summary)
        selected_property_id = selected_summary.property_id

    st.markdown("---")
    _render_priorities(daily_result, selected_property_id)
    st.markdown("---")
    _render_latest_result(controller)
    _render_review(controller)

    if debug_mode and controller.result is not None:
        _render_debug(controller.result)


if __name__ == "__main__":
    main()
