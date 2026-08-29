"""Independent behavior and evidence-boundary tests for Phase 3 specialists."""

from __future__ import annotations

from datetime import date, time

import pytest

from src.agents import BookingAgent, GuestAgent, MaintenanceAgent, TurnoverAgent
from src.models import (
    BookingAgentInput,
    EvidenceSource,
    FindingCategory,
    FindingSeverity,
    GuestAgentInput,
    MaintenanceAgentInput,
    SpecialistName,
    SpecialistOutput,
    TurnoverAgentInput,
)
from src.tools import (
    FailureSimulator,
    ReadToolName,
    SimulatedFailureConfig,
    get_cleaning_schedule,
    get_guest_messages,
    get_maintenance_tickets,
    get_property_rules,
    get_reservations,
)


OPERATING_DATE = date(2026, 8, 28)


def items(result):
    assert result.success is True
    return result.items


def finding_by_category(output: SpecialistOutput, category: FindingCategory):
    return next(finding for finding in output.findings if finding.category == category)


def test_booking_agent_finds_lake_house_same_day_turnover() -> None:
    reservations = items(
        get_reservations(
            ["prop_lake_house"],
            start_date=OPERATING_DATE,
            end_date=OPERATING_DATE,
        )
    )

    output = BookingAgent().invoke(
        BookingAgentInput(
            property_scope=["prop_lake_house"],
            date_scope="2026-08-28",
            reservations=reservations,
        )
    )

    turnover = finding_by_category(output, FindingCategory.SAME_DAY_TURNOVER)
    assert output.specialist == SpecialistName.BOOKING
    assert turnover.severity == FindingSeverity.MEDIUM
    assert turnover.requires_attention is True
    assert turnover.evidence[0].record_ids == ["res_lake_001", "res_lake_002"]
    assert FindingCategory.ARRIVAL in {finding.category for finding in output.findings}
    assert FindingCategory.DEPARTURE in {finding.category for finding in output.findings}


def test_booking_agent_detects_conflict_only_from_supplied_reservations() -> None:
    reservations = items(get_reservations(["prop_lake_house"]))
    overlapping = reservations[1].model_copy(
        update={"check_in_date": date(2026, 8, 27)}
    )

    output = BookingAgent().invoke(
        {
            "property_scope": ["prop_lake_house"],
            "date_scope": None,
            "reservations": [reservations[0], overlapping],
        }
    )

    conflict = finding_by_category(output, FindingCategory.RESERVATION_CONFLICT)
    assert conflict.severity == FindingSeverity.CRITICAL
    assert set(conflict.evidence[0].record_ids) == {"res_lake_001", "res_lake_002"}


def test_booking_agent_reports_booking_gap_without_escalating_it() -> None:
    reservations = items(get_reservations(["prop_downtown_suite"]))

    output = BookingAgent().invoke(
        {
            "property_scope": ["prop_downtown_suite"],
            "date_scope": None,
            "reservations": reservations,
        }
    )

    gap = finding_by_category(output, FindingCategory.BOOKING_GAP)
    assert gap.severity == FindingSeverity.LOW
    assert gap.requires_attention is False
    assert "4-night" in gap.summary


def test_guest_agent_prioritizes_only_unanswered_inbound_messages() -> None:
    messages = items(
        get_guest_messages(
            ["prop_pine_house", "prop_beach_bungalow", "prop_city_loft"],
            start_date=date(2026, 8, 27),
            end_date=OPERATING_DATE,
        )
    )

    output = GuestAgent().invoke(
        GuestAgentInput(
            property_scope=[],
            date_scope="2026-08-27/2026-08-28",
            guest_messages=messages,
        )
    )

    maintenance_report = finding_by_category(
        output, FindingCategory.GUEST_MAINTENANCE_REPORT
    )
    early_check_in = finding_by_category(
        output, FindingCategory.EARLY_CHECK_IN_REQUEST
    )
    assert maintenance_report.severity == FindingSeverity.HIGH
    assert maintenance_report.evidence[0].record_ids == ["msg_pine_001"]
    assert early_check_in.severity == FindingSeverity.MEDIUM
    assert early_check_in.evidence[0].record_ids == ["msg_beach_001"]
    assert all("msg_city" not in finding.finding_id for finding in output.findings)


def test_turnover_agent_escalates_missing_same_day_confirmation() -> None:
    reservations = items(
        get_reservations(
            ["prop_lake_house"],
            start_date=OPERATING_DATE,
            end_date=OPERATING_DATE,
        )
    )
    cleanings = items(
        get_cleaning_schedule(
            ["prop_lake_house"],
            start_date=OPERATING_DATE,
            end_date=OPERATING_DATE,
        )
    )

    output = TurnoverAgent().invoke(
        TurnoverAgentInput(
            property_scope=["prop_lake_house"],
            date_scope="2026-08-28",
            reservations=reservations,
            cleaning_schedule=cleanings,
        )
    )

    missing = finding_by_category(
        output, FindingCategory.CLEANER_CONFIRMATION_MISSING
    )
    assert missing.severity == FindingSeverity.HIGH
    assert missing.requires_attention is True
    evidence_by_source = {evidence.source: evidence for evidence in missing.evidence}
    assert evidence_by_source[EvidenceSource.CLEANING_SCHEDULE].record_ids == [
        "clean_lake_001"
    ]
    assert set(evidence_by_source[EvidenceSource.RESERVATIONS].record_ids) == {
        "res_lake_001",
        "res_lake_002",
    }


def test_turnover_agent_reports_confirmed_city_cleaning_without_overclaiming_readiness() -> None:
    reservations = items(get_reservations(["prop_city_loft"]))
    cleanings = items(get_cleaning_schedule(["prop_city_loft"]))
    rules = items(get_property_rules(["prop_city_loft"]))

    output = TurnoverAgent().invoke(
        TurnoverAgentInput(
            property_scope=["prop_city_loft"],
            date_scope="2026-08-28",
            reservations=reservations,
            cleaning_schedule=cleanings,
            property_rules=rules,
        )
    )

    on_track = finding_by_category(output, FindingCategory.TURNOVER_ON_TRACK)
    assert on_track.severity == FindingSeverity.LOW
    assert on_track.requires_attention is False
    assert "cleaning is confirmed" in on_track.summary.lower()
    assert "property is ready" not in on_track.summary.lower()
    assert any(
        evidence.source == EvidenceSource.PROPERTY_RULES
        for evidence in on_track.evidence
    )


def test_turnover_agent_applies_property_cleaner_ready_buffer() -> None:
    reservations = items(get_reservations(["prop_city_loft"]))
    cleaning = items(get_cleaning_schedule(["prop_city_loft"]))[0]
    rules = items(get_property_rules(["prop_city_loft"]))
    late_for_buffer = cleaning.model_copy(update={"target_complete_time": time(14, 0)})

    output = TurnoverAgent().invoke(
        TurnoverAgentInput(
            property_scope=["prop_city_loft"],
            date_scope="2026-08-28",
            reservations=reservations,
            cleaning_schedule=[late_for_buffer],
            property_rules=rules,
        )
    )

    timing = finding_by_category(output, FindingCategory.TURNOVER_TIMING_RISK)
    evidence_by_source = {evidence.source: evidence for evidence in timing.evidence}
    assert evidence_by_source[EvidenceSource.PROPERTY_RULES].record_ids == [
        "rule_city_loft"
    ]


def test_turnover_agent_detects_timing_risk_and_missing_schedule() -> None:
    reservations = items(get_reservations(["prop_city_loft"]))
    cleaning = items(get_cleaning_schedule(["prop_city_loft"]))[0]
    late_cleaning = cleaning.model_copy(update={"target_complete_time": time(15, 0)})

    timing_output = TurnoverAgent().invoke(
        {
            "property_scope": ["prop_city_loft"],
            "date_scope": "2026-08-28",
            "reservations": reservations,
            "cleaning_schedule": [late_cleaning],
        }
    )
    timing = finding_by_category(timing_output, FindingCategory.TURNOVER_TIMING_RISK)
    assert timing.severity == FindingSeverity.CRITICAL

    arrival = next(item for item in reservations if item.id == "res_city_002")
    missing_output = TurnoverAgent().invoke(
        {
            "property_scope": ["prop_city_loft"],
            "date_scope": "2026-08-28",
            "reservations": [arrival],
            "cleaning_schedule": [],
        }
    )
    missing = finding_by_category(
        missing_output, FindingCategory.CLEANING_SCHEDULE_MISSING
    )
    assert missing.severity == FindingSeverity.HIGH


def test_maintenance_agent_connects_blocking_ticket_to_supplied_upcoming_stay() -> None:
    tickets = items(get_maintenance_tickets(["prop_pine_house"]))
    reservations = items(get_reservations(["prop_pine_house"]))

    output = MaintenanceAgent().invoke(
        MaintenanceAgentInput(
            property_scope=["prop_pine_house"],
            date_scope="2026-08-28",
            maintenance_tickets=tickets,
            reservations=reservations,
        )
    )

    risk = finding_by_category(
        output, FindingCategory.UPCOMING_STAY_MAINTENANCE_RISK
    )
    assert risk.severity == FindingSeverity.HIGH
    evidence_by_source = {evidence.source: evidence for evidence in risk.evidence}
    assert evidence_by_source[EvidenceSource.MAINTENANCE_TICKETS].record_ids == [
        "maint_pine_001"
    ]
    assert evidence_by_source[EvidenceSource.RESERVATIONS].record_ids == ["res_pine_002"]


def test_maintenance_agent_keeps_nonblocking_vacant_issue_at_source_severity() -> None:
    tickets = items(get_maintenance_tickets(["prop_mountain_retreat"]))

    output = MaintenanceAgent().invoke(
        {
            "property_scope": ["prop_mountain_retreat"],
            "date_scope": "2026-08-28",
            "maintenance_tickets": tickets,
            "reservations": [],
        }
    )

    finding = finding_by_category(output, FindingCategory.OPEN_MAINTENANCE)
    assert finding.severity == FindingSeverity.MEDIUM
    assert "guest" not in finding.summary.lower()


def test_maintenance_agent_does_not_reopen_resolved_ticket() -> None:
    tickets = items(get_maintenance_tickets(["prop_lake_house"]))

    output = MaintenanceAgent().invoke(
        {
            "property_scope": ["prop_lake_house"],
            "date_scope": None,
            "maintenance_tickets": tickets,
            "reservations": [],
        }
    )

    assert output.findings == []
    assert output.analyzed_record_ids == ["maint_lake_001"]


def test_source_failure_warns_and_prevents_unsupported_findings() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_CLEANING_SCHEDULE: 1}
        )
    )
    failed_cleaning = get_cleaning_schedule(failure_simulator=simulator)
    reservations = items(get_reservations(["prop_lake_house"]))
    assert failed_cleaning.error is not None

    output = TurnoverAgent().invoke(
        {
            "property_scope": ["prop_lake_house"],
            "date_scope": "2026-08-28",
            "reservations": reservations,
            "cleaning_schedule": [],
            "source_errors": [failed_cleaning.error],
        }
    )

    assert output.findings == []
    assert len(output.warnings) == 1
    assert output.warnings[0].source_tool == "get_cleaning_schedule"
    assert output.warnings[0].retryable is True


def test_reservation_failure_prevents_maintenance_agent_from_claiming_stay_impact() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_RESERVATIONS: 1}
        )
    )
    failed_reservations = get_reservations(failure_simulator=simulator)
    tickets = items(get_maintenance_tickets(["prop_pine_house"]))
    assert failed_reservations.error is not None

    output = MaintenanceAgent().invoke(
        {
            "property_scope": ["prop_pine_house"],
            "date_scope": "2026-08-28",
            "maintenance_tickets": tickets,
            "reservations": [],
            "source_errors": [failed_reservations.error],
        }
    )

    finding = finding_by_category(output, FindingCategory.GUEST_IMPACTING_MAINTENANCE)
    assert finding.category != FindingCategory.UPCOMING_STAY_MAINTENANCE_RISK
    assert len(output.warnings) == 1


@pytest.mark.parametrize(
    ("agent", "input_model"),
    [
        (BookingAgent(), BookingAgentInput),
        (GuestAgent(), GuestAgentInput),
        (TurnoverAgent(), TurnoverAgentInput),
        (MaintenanceAgent(), MaintenanceAgentInput),
    ],
)
def test_each_specialist_is_a_typed_independent_langchain_runnable(
    agent, input_model
) -> None:
    assert agent.runnable.get_input_schema() is input_model
    assert agent.runnable.get_output_schema() is SpecialistOutput
    assert "executed_actions" not in SpecialistOutput.model_fields
    for prohibited_method in (
        "send_guest_message",
        "send_cleaner_message",
        "update_maintenance_status",
    ):
        assert not hasattr(agent, prohibited_method)
