"""Behavior tests for the Phase 1 read-only operational tools."""

from __future__ import annotations

from datetime import date

import pytest

from src.models import (
    CleaningSchedule,
    GuestMessage,
    MaintenanceTicket,
    Property,
    PropertyRule,
    Reservation,
)
from src.tools import (
    FailureSimulator,
    ReadToolName,
    SimulatedFailureConfig,
    ToolErrorCode,
    get_cleaning_schedule,
    get_guest_messages,
    get_maintenance_tickets,
    get_properties,
    get_property_rules,
    get_reservations,
)


OPERATING_DATE = date(2026, 8, 28)


def test_get_properties_returns_typed_filtered_records() -> None:
    result = get_properties(["prop_lake_house", "prop_city_loft"])

    assert result.success is True
    assert result.error is None
    assert {item.id for item in result.items} == {
        "prop_lake_house",
        "prop_city_loft",
    }
    assert all(isinstance(item, Property) for item in result.items)
    assert result.metadata.returned_count == 2
    assert result.metadata.filters["property_ids"] == [
        "prop_city_loft",
        "prop_lake_house",
    ]


def test_get_property_rules_returns_typed_scoped_rules() -> None:
    result = get_property_rules(["prop_city_loft"])

    assert result.success is True
    assert [item.id for item in result.items] == ["rule_city_loft"]
    assert isinstance(result.items[0], PropertyRule)
    assert result.items[0].cleaner_ready_buffer_minutes == 90


def test_get_reservations_filters_by_property_and_overlapping_date() -> None:
    result = get_reservations(
        ["prop_lake_house"],
        start_date=OPERATING_DATE,
        end_date=OPERATING_DATE,
    )

    assert result.success is True
    assert {item.id for item in result.items} == {"res_lake_001", "res_lake_002"}
    assert all(isinstance(item, Reservation) for item in result.items)


def test_get_guest_messages_uses_message_local_calendar_date() -> None:
    result = get_guest_messages(
        ["prop_beach_bungalow"],
        start_date=date(2026, 8, 27),
        end_date=date(2026, 8, 27),
    )

    assert result.success is True
    assert [item.id for item in result.items] == ["msg_beach_001"]
    assert isinstance(result.items[0], GuestMessage)


def test_get_cleaning_schedule_filters_same_day_jobs() -> None:
    result = get_cleaning_schedule(
        start_date=OPERATING_DATE,
        end_date=OPERATING_DATE,
    )

    assert result.success is True
    assert {item.property_id for item in result.items} == {
        "prop_lake_house",
        "prop_city_loft",
        "prop_beach_bungalow",
    }
    assert all(isinstance(item, CleaningSchedule) for item in result.items)


def test_get_maintenance_tickets_treats_unresolved_ticket_as_active() -> None:
    result = get_maintenance_tickets(
        start_date=OPERATING_DATE,
        end_date=OPERATING_DATE,
    )

    assert result.success is True
    assert {item.id for item in result.items} == {
        "maint_pine_001",
        "maint_mountain_001",
    }
    assert all(isinstance(item, MaintenanceTicket) for item in result.items)


def test_empty_property_filter_returns_a_successful_empty_result() -> None:
    result = get_properties([])

    assert result.success is True
    assert result.items == []
    assert result.metadata.returned_count == 0


@pytest.mark.parametrize(
    "tool",
    [
        get_reservations,
        get_guest_messages,
        get_cleaning_schedule,
        get_maintenance_tickets,
    ],
)
def test_date_tools_return_structured_error_for_reversed_range(tool) -> None:
    result = tool(start_date=date(2026, 8, 29), end_date=OPERATING_DATE)

    assert result.success is False
    assert result.items == []
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_FILTER
    assert result.error.retryable is False
    assert result.metadata.returned_count == 0


def test_property_filter_rejects_a_bare_string_without_throwing() -> None:
    result = get_properties("prop_lake_house")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_FILTER


def test_simulated_transient_failure_recovers_on_next_call() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={ReadToolName.GET_PROPERTIES: 1},
            message="Synthetic provider timeout.",
        )
    )

    failed = get_properties(failure_simulator=simulator)
    recovered = get_properties(failure_simulator=simulator)

    assert failed.success is False
    assert failed.error is not None
    assert failed.error.code == ToolErrorCode.SIMULATED_FAILURE
    assert failed.error.retryable is True
    assert failed.error.details["attempt"] == 1
    assert recovered.success is True
    assert len(recovered.items) == 8
    assert simulator.attempt_count(ReadToolName.GET_PROPERTIES) == 2


def test_failure_budgets_are_independent_per_tool() -> None:
    simulator = FailureSimulator(
        SimulatedFailureConfig(
            failures_before_success={
                ReadToolName.GET_RESERVATIONS: 1,
                ReadToolName.GET_GUEST_MESSAGES: 2,
            }
        )
    )

    assert get_reservations(failure_simulator=simulator).success is False
    assert get_reservations(failure_simulator=simulator).success is True
    assert get_guest_messages(failure_simulator=simulator).success is False
    assert get_guest_messages(failure_simulator=simulator).success is False
    assert get_guest_messages(failure_simulator=simulator).success is True


def test_missing_dataset_returns_retryable_structured_error(tmp_path) -> None:
    result = get_properties(data_dir=tmp_path)

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.DATA_UNAVAILABLE
    assert result.error.retryable is True
    assert "properties.json" in result.error.details["path"]


def test_malformed_dataset_returns_non_retryable_structured_error(tmp_path) -> None:
    (tmp_path / "properties.json").write_text("{not valid json", encoding="utf-8")

    result = get_properties(data_dir=tmp_path)

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_DATA
    assert result.error.retryable is False
