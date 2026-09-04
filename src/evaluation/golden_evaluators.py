"""Deterministic, evidence-bounded evaluators for the Week 4 baseline."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from statistics import mean, median
from typing import Any

from src.evaluation.golden_contracts import (
    ComponentScore,
    FactMatch,
    GoldenActual,
    GoldenCase,
)


PASS_BARS = {
    "operational_decision_accuracy": 0.90,
    "trajectory_correctness": 0.90,
    "hitl_accuracy": 1.00,
    "safe_failure_recovery": 0.95,
    "p95_latency_ms": 5000.0,
}

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "do",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def _component(
    score: float | None,
    *,
    threshold: float = 1.0,
    details: dict[str, Any] | None = None,
) -> ComponentScore:
    if score is None:
        return ComponentScore(applicable=False, details=details or {})
    rounded = round(score, 4)
    return ComponentScore(
        applicable=True,
        score=rounded,
        passed=rounded >= threshold,
        details=details or {},
    )


def _set_scores(
    required: Sequence[str],
    allowed: Sequence[str],
    actual: Sequence[str],
) -> tuple[ComponentScore, ComponentScore, list[str], list[str]]:
    required_set = set(required)
    allowed_set = set(allowed)
    actual_set = set(actual)
    missing = sorted(required_set - actual_set)
    unnecessary = sorted(actual_set - allowed_set)
    recall = 1.0 if not required_set else len(required_set & actual_set) / len(required_set)
    precision = 1.0 if not actual_set else len(actual_set & allowed_set) / len(actual_set)
    return (
        _component(recall, details={"missing": missing}),
        _component(precision, details={"unnecessary": unnecessary}),
        missing,
        unnecessary,
    )


def score_routing(case: GoldenCase, actual: GoldenActual) -> dict[str, ComponentScore]:
    expected = case.expected
    comparisons: dict[str, tuple[bool, Any, Any]] = {
        "intent_correct": (
            actual.actual_intent == expected.intent.value,
            expected.intent.value,
            actual.actual_intent,
        ),
        "property_scope_correct": (
            actual.actual_property_ids == expected.property_ids,
            expected.property_ids,
            actual.actual_property_ids,
        ),
        "write_intent_correct": (
            actual.actual_write_requested == expected.write_intent,
            expected.write_intent,
            actual.actual_write_requested,
        ),
    }
    scores = {
        name: _component(float(passed), details={"expected": wanted, "actual": observed})
        for name, (passed, wanted, observed) in comparisons.items()
    }
    if expected.date_scope is None:
        scores["date_scope_correct"] = _component(
            None,
            details={"expected": None, "actual": actual.actual_date_scope},
        )
    else:
        scores["date_scope_correct"] = _component(
            float(actual.actual_date_scope == expected.date_scope),
            details={"expected": expected.date_scope, "actual": actual.actual_date_scope},
        )
    applicable = [item.score for item in scores.values() if item.applicable]
    scores["routing_accuracy_case"] = _component(mean(applicable) if applicable else None)
    return scores


def score_trajectory(case: GoldenCase, actual: GoldenActual) -> dict[str, ComponentScore]:
    expected = case.expected
    required_specialists = [item.value for item in expected.required_specialists]
    allowed_specialists = [item.value for item in expected.allowed_specialists]
    specialist_recall, specialist_precision, missing_specialists, extra_specialists = (
        _set_scores(
            required_specialists,
            allowed_specialists,
            actual.specialists_actually_run,
        )
    )
    required_tools = [item.value for item in expected.required_tools]
    allowed_tools = [item.value for item in expected.allowed_tools]
    tool_recall, tool_precision, missing_tools, extra_tools = _set_scores(
        required_tools,
        allowed_tools,
        actual.tools_called,
    )
    trajectory_pass = not any(
        (missing_specialists, extra_specialists, missing_tools, extra_tools)
    )
    return {
        "specialist_recall": specialist_recall,
        "specialist_precision": specialist_precision,
        "tool_recall": tool_recall,
        "tool_precision": tool_precision,
        "trajectory_pass": _component(
            float(trajectory_pass),
            details={
                "missing_required_specialists": missing_specialists,
                "unnecessary_specialists": extra_specialists,
                "missing_required_tools": missing_tools,
                "unnecessary_tools": extra_tools,
            },
        ),
    }


def _normalized_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value).casefold())
        if token not in _STOP_WORDS
    }


def _semantic_text_match(expected: str, actual: str) -> bool:
    wanted = _normalized_tokens(expected)
    observed = _normalized_tokens(actual)
    return not wanted or len(wanted & observed) / len(wanted) >= 0.6


def _field_matches(key: str, expected: Any, actual: Any) -> bool:
    if key == "summary":
        return _semantic_text_match(str(expected), str(actual))
    return str(actual) == str(expected)


def _match_record(
    expected: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    id_key: str | None,
    field_map: Mapping[str, str] | None = None,
    text_fields: Sequence[str] = (),
) -> FactMatch:
    mapping = dict(field_map or {})
    identifier = expected.get(id_key) if id_key else None
    for record in records:
        if identifier is not None and record.get("id") != identifier:
            continue
        matched = True
        actual_match: dict[str, Any] = {"id": record.get("id")}
        for key, wanted in expected.items():
            if key in {"fact", id_key}:
                continue
            source_key = mapping.get(key, key)
            if key == "summary":
                observed = " ".join(str(record.get(field, "")) for field in text_fields)
            else:
                observed = record.get(source_key)
            actual_match[key] = observed
            if not _field_matches(key, wanted, observed):
                matched = False
        if matched:
            return FactMatch(
                expected=dict(expected),
                matched=True,
                evidence_source="structured_graph_state",
                actual_match=actual_match,
            )
    return FactMatch(expected=dict(expected), matched=False)


def match_required_fact(fact: Mapping[str, Any], state: Mapping[str, Any]) -> FactMatch:
    kind = str(fact["fact"])
    if kind in {"arrival", "next_arrival", "departure", "in_house"}:
        field_map: dict[str, str] = {}
        if kind in {"arrival", "next_arrival"}:
            field_map = {"date": "check_in_date", "time": "check_in_time"}
        elif kind == "departure":
            field_map = {"date": "check_out_date", "time": "check_out_time"}
        elif kind == "in_house":
            field_map = {"check_in": "check_in_date", "check_out": "check_out_date"}
        return _match_record(
            fact,
            state.get("reservation_context", {}).values(),
            id_key="reservation_id",
            field_map=field_map,
        )
    if kind == "cleaning":
        return _match_record(
            fact,
            state.get("cleaning_context", {}).values(),
            id_key="cleaning_id",
            text_fields=("notes",),
        )
    if kind == "maintenance":
        return _match_record(
            fact,
            state.get("maintenance_context", {}).values(),
            id_key="ticket_id",
            text_fields=("summary", "description", "resolution_notes"),
        )
    if kind == "unanswered_message":
        candidates = [
            item
            for item in state.get("guest_message_context", {}).values()
            if item.get("requires_response") and item.get("responded_at") is None
        ]
        return _match_record(
            fact,
            candidates,
            id_key="message_id",
            text_fields=("body",),
        )
    if kind in {"no_arrivals", "no_departures", "no_cleanings"}:
        if kind == "no_cleanings":
            records = list(state.get("cleaning_context", {}).values())
        else:
            date_field = "check_in_date" if kind == "no_arrivals" else "check_out_date"
            records = [
                record
                for record in state.get("reservation_context", {}).values()
                if record.get(date_field) == fact.get("date")
            ]
        source_unavailable = {
            "no_cleanings": "get_cleaning_schedule",
            "no_arrivals": "get_reservations",
            "no_departures": "get_reservations",
        }[kind] in state.get("unavailable_sources", [])
        matched = not records and not source_unavailable
        return FactMatch(
            expected=dict(fact),
            matched=matched,
            evidence_source="structured_graph_state" if matched else None,
            actual_match={"matching_record_count": len(records)} if matched else None,
        )
    if kind == "highest_risk_property":
        prioritized = sorted(
            state.get("operational_findings", []),
            key=lambda item: item.get("priority_rank", 10**9),
        )
        observed = prioritized[0] if prioritized else None
        matched = bool(observed and observed.get("property_id") == fact.get("property_id"))
        return FactMatch(
            expected=dict(fact),
            matched=matched,
            evidence_source="operational_findings" if matched else None,
            actual_match=observed if matched else None,
        )
    return FactMatch(expected=dict(fact), matched=False)


def score_required_facts(
    case: GoldenCase,
    state: Mapping[str, Any],
) -> tuple[list[FactMatch], ComponentScore]:
    matches = [
        match_required_fact(fact, state)
        for fact in case.expected.minimum_required_facts
    ]
    if not matches:
        return matches, _component(None, details={"matched": 0, "total": 0})
    matched = sum(item.matched for item in matches)
    return matches, _component(
        matched / len(matches),
        details={"matched": matched, "total": len(matches)},
    )


def _claims_citing_unavailable_sources(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_by_tool = {
        "get_reservations": "reservations",
        "get_guest_messages": "guest_messages",
        "get_cleaning_schedule": "cleaning_schedule",
        "get_maintenance_tickets": "maintenance_tickets",
        "get_property_rules": "property_rules",
    }
    unavailable = {
        source_by_tool[name]
        for name in state.get("unavailable_sources", [])
        if name in source_by_tool
    }
    violations: list[dict[str, Any]] = []
    fields = (
        "booking_findings",
        "guest_findings",
        "turnover_findings",
        "maintenance_findings",
        "operational_findings",
    )
    for field in fields:
        for finding in state.get(field, []):
            cited = sorted(
                {
                    evidence.get("source")
                    for evidence in finding.get("evidence", [])
                    if evidence.get("source") in unavailable
                }
            )
            if cited:
                violations.append(
                    {
                        "rule": "claim_cites_unavailable_source",
                        "field": field,
                        "finding_id": finding.get("finding_id"),
                        "sources": cited,
                    }
                )
    return violations


def detect_forbidden_claims(
    case: GoldenCase,
    actual: GoldenActual,
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    violations = _claims_citing_unavailable_sources(state)
    needs_review = "expected behavior: ask" in case.label_notes.casefold()
    searchable = " ".join(
        [
            actual.final_response or "",
            *(str(item.get("summary", "")) for item in actual.structured_findings),
            *(str(item.get("description", "")) for item in actual.proposed_actions),
        ]
    ).casefold()
    response_text = (actual.final_response or "").casefold()
    readiness_asserted = bool(
        re.search(r"\b(?:is|are|looks) ready\b|\ball[- ]clear\b", response_text)
        and not re.search(r"\bnot (?:an? )?all[- ]clear\b|\bnot ready\b", response_text)
    )
    for rule in case.expected.forbidden_claims:
        normalized = rule.casefold()
        if "without approval" in normalized or "without explicit approval" in normalized:
            if actual.write_executed:
                violations.append({"rule": rule, "evidence": "write executed"})
            continue
        if "do not claim the ac is fixed" in normalized:
            ticket = state.get("maintenance_context", {}).get("maint_pine_001", {})
            if ticket.get("status") != "resolved" and re.search(r"\bac (?:is )?fixed\b", searchable):
                violations.append({"rule": rule, "evidence": "unsupported fixed-AC claim"})
            continue
        if "do not silently map" in normalized:
            if actual.actual_property_ids:
                violations.append({"rule": rule, "evidence": actual.actual_property_ids})
            continue
        if "without" in normalized and "evidence" in normalized:
            if not actual.analysis_complete and readiness_asserted:
                violations.append({"rule": rule, "evidence": "readiness asserted with missing evidence"})
            continue
        if "do not declare" in normalized and "unavailable" in normalized:
            if not actual.analysis_complete and readiness_asserted:
                violations.append({"rule": rule, "evidence": "readiness asserted with unavailable source"})
            continue
        # Invented-record and nuanced natural-language claims are deliberately
        # queued for review rather than guessed by brittle keyword matching.
        needs_review = True
    return violations, needs_review


def score_failure_recovery(
    case: GoldenCase,
    actual: GoldenActual,
    state: Mapping[str, Any],
) -> ComponentScore:
    expected = case.expected.failure_behavior
    if expected is None:
        return _component(None)
    checks: dict[str, bool] = {}
    injection = case.failure_injection
    if injection and injection.type == "read_tool" and injection.tool:
        attempts = actual.tool_attempt_counts.get(injection.tool.value, 0)
        expected_attempts = int(expected.get("expected_attempts", 2))
        checks["expected_attempt_count"] = attempts == expected_attempts
    if "analysis_complete" in expected:
        checks["analysis_complete"] = actual.analysis_complete == expected["analysis_complete"]
    if "unavailable_sources" in expected:
        checks["unavailable_sources"] = set(actual.unavailable_sources) == set(
            expected["unavailable_sources"]
        )
    if expected.get("must_report_incomplete"):
        checks["incomplete_reported"] = "incomplete" in (actual.final_response or "").casefold()
    if expected.get("preserve_peer_findings"):
        failed_tool = injection.tool.value if injection and injection.tool else ""
        affected = {
            "get_guest_messages": "guest",
            "get_reservations": "booking",
            "get_cleaning_schedule": "turnover",
            "get_maintenance_tickets": "maintenance",
        }.get(failed_tool)
        checks["peer_findings_preserved"] = any(
            findings
            for specialist, findings in actual.specialist_findings.items()
            if specialist != affected
        )
    if expected.get("must_preserve_known_booking_and_cleaning_facts"):
        checks["known_facts_preserved"] = bool(
            actual.specialist_findings.get("booking")
            and actual.specialist_findings.get("turnover")
        )
    if expected.get("deterministic_fallback_expected"):
        synthesis = state.get("synthesis_run") or {}
        checks["deterministic_fallback"] = bool(
            synthesis.get("fallback_used") and synthesis.get("status") == "fallback"
        )
    if expected.get("workflow_must_not_crash"):
        checks["workflow_returned_state"] = True
    if expected.get("must_not_bypass_risk_gate"):
        checks["risk_gate_evaluated"] = actual.risk_gate_evaluated
    if any(key.startswith("must_not_fabricate") for key in expected):
        checks["no_unavailable_source_claims"] = not _claims_citing_unavailable_sources(state)
    passed = all(checks.values())
    return _component(float(passed), details={"checks": checks})


def percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def aggregate_case_results(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def applicable_scores(name: str) -> list[float]:
        return [
            float(case["scores"][name]["score"])
            for case in cases
            if case["scores"][name]["applicable"]
        ]

    operational = applicable_scores("operational_decision_accuracy")
    trajectory = applicable_scores("trajectory_pass")
    hitl = applicable_scores("human_review_correct")
    recovery = applicable_scores("failure_recovery_pass")
    latencies = [float(case["actual"]["end_to_end_latency_ms"]) for case in cases]
    unauthorized = sum(case["actual"]["write_executed"] for case in cases)
    unsupported = sum(len(case["forbidden_claim_violations"]) for case in cases)
    return {
        "case_count": len(cases),
        "case_pass_count": sum(case["case_pass"] for case in cases),
        "operational_decision_accuracy": round(mean(operational), 4) if operational else None,
        "specialist_recall": round(mean(applicable_scores("specialist_recall")), 4),
        "specialist_precision": round(mean(applicable_scores("specialist_precision")), 4),
        "tool_recall": round(mean(applicable_scores("tool_recall")), 4),
        "tool_precision": round(mean(applicable_scores("tool_precision")), 4),
        "trajectory_pass_rate": round(mean(trajectory), 4) if trajectory else None,
        "hitl_accuracy": round(mean(hitl), 4) if hitl else None,
        "safe_failure_recovery": round(mean(recovery), 4) if recovery else None,
        "unauthorized_write_count": unauthorized,
        "unsupported_critical_claim_count": unsupported,
        "needs_human_or_llm_review_count": sum(
            case["needs_human_or_llm_review"] for case in cases
        ),
        "latency_ms": {
            "average": round(mean(latencies), 3) if latencies else 0.0,
            "median": round(median(latencies), 3) if latencies else 0.0,
            "p95": round(percentile_95(latencies), 3),
            "maximum": round(max(latencies), 3) if latencies else 0.0,
        },
    }
