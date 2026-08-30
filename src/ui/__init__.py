"""Presentation helpers for the StayOps Streamlit dashboard."""

from src.ui.date_context import (
    format_answer_date_context,
    format_date_context,
    format_scope_context,
    format_short_date,
    operations_copy,
    parse_date_scope,
    readiness_copy,
    single_date_from_scope,
)
from src.ui.dashboard import (
    ActivityStatus,
    ActivityStep,
    DEFAULT_DAILY_QUERY,
    DashboardController,
    PropertyHealth,
    PropertySummary,
    build_property_summaries,
    count_property_health,
    evidence_for_action,
    incomplete_analysis_message,
)

__all__ = [
    "ActivityStatus",
    "ActivityStep",
    "DEFAULT_DAILY_QUERY",
    "DashboardController",
    "PropertyHealth",
    "PropertySummary",
    "build_property_summaries",
    "count_property_health",
    "evidence_for_action",
    "format_answer_date_context",
    "format_date_context",
    "format_scope_context",
    "format_short_date",
    "incomplete_analysis_message",
    "operations_copy",
    "parse_date_scope",
    "readiness_copy",
    "single_date_from_scope",
]
