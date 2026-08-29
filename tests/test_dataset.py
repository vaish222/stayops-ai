"""Validation and scenario coverage for the Phase 0 synthetic fixtures."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models import (
    ConfirmationStatus,
    MaintenanceSeverity,
    MaintenanceStatus,
    MessageCategory,
    StayOpsDataset,
)


DATA_DIR = Path(__file__).parents[1] / "data"
OPERATING_DATE = date(2026, 8, 28)
EXPECTED_PROPERTIES = {
    "Lake House",
    "Pine House",
    "City Loft",
    "Garden Cottage",
    "Sunset House",
    "Beach Bungalow",
    "Mountain Retreat",
    "Downtown Suite",
}


def load_json(filename: str) -> list[dict]:
    with (DATA_DIR / filename).open(encoding="utf-8") as data_file:
        return json.load(data_file)


@pytest.fixture(scope="module")
def dataset() -> StayOpsDataset:
    return StayOpsDataset(
        properties=load_json("properties.json"),
        reservations=load_json("reservations.json"),
        guest_messages=load_json("guest_messages.json"),
        cleaning_schedule=load_json("cleaning_schedule.json"),
        maintenance_tickets=load_json("maintenance_tickets.json"),
        property_rules=load_json("property_rules.json"),
    )


def test_all_six_datasets_parse_as_pydantic_models(dataset: StayOpsDataset) -> None:
    assert {prop.name for prop in dataset.properties} == EXPECTED_PROPERTIES
    assert len(dataset.properties) == 8
    assert len(dataset.property_rules) == 8
    assert all(record.is_synthetic for group in (
        dataset.properties,
        dataset.reservations,
        dataset.guest_messages,
        dataset.cleaning_schedule,
        dataset.maintenance_tickets,
        dataset.property_rules,
    ) for record in group)


def test_expanded_operational_data_covers_every_property(
    dataset: StayOpsDataset,
) -> None:
    property_ids = {prop.id for prop in dataset.properties}
    reservations_by_property = Counter(
        item.property_id for item in dataset.reservations
    )
    messages_by_property = Counter(
        item.property_id for item in dataset.guest_messages
    )
    cleanings_by_property = Counter(
        item.property_id for item in dataset.cleaning_schedule
    )
    maintenance_by_property = Counter(
        item.property_id for item in dataset.maintenance_tickets
    )

    assert len(dataset.reservations) == 21
    assert len(dataset.guest_messages) == 17
    assert len(dataset.cleaning_schedule) == 16
    assert len(dataset.maintenance_tickets) == 14
    assert all(reservations_by_property[property_id] >= 2 for property_id in property_ids)
    assert all(messages_by_property[property_id] >= 1 for property_id in property_ids)
    assert all(cleanings_by_property[property_id] >= 1 for property_id in property_ids)
    assert all(maintenance_by_property[property_id] >= 1 for property_id in property_ids)


def test_lake_house_has_unconfirmed_same_day_turnover(dataset: StayOpsDataset) -> None:
    cleaning = next(item for item in dataset.cleaning_schedule if item.property_id == "prop_lake_house")
    reservations = {item.id: item for item in dataset.reservations}

    assert cleaning.scheduled_date == OPERATING_DATE
    assert cleaning.confirmation_status == ConfirmationStatus.PENDING
    assert reservations[cleaning.checkout_reservation_id].check_out_date == OPERATING_DATE
    assert reservations[cleaning.next_reservation_id].check_in_date == OPERATING_DATE


def test_pine_house_has_guest_impacting_ac_issue_and_tomorrow_arrival(
    dataset: StayOpsDataset,
) -> None:
    ticket = next(item for item in dataset.maintenance_tickets if item.id == "maint_pine_001")
    message = next(item for item in dataset.guest_messages if item.id == "msg_pine_001")
    arrivals = [
        item
        for item in dataset.reservations
        if item.property_id == "prop_pine_house"
        and item.check_in_date == date(2026, 8, 29)
    ]

    assert ticket.severity == MaintenanceSeverity.HIGH
    assert ticket.status == MaintenanceStatus.OPEN
    assert ticket.guest_impact is True
    assert ticket.blocks_checkin is True
    assert message.responded_at is None and message.requires_response
    assert len(arrivals) == 1


def test_city_loft_turnover_is_confirmed_for_three_pm_arrival(
    dataset: StayOpsDataset,
) -> None:
    cleaning = next(item for item in dataset.cleaning_schedule if item.property_id == "prop_city_loft")
    arrival = next(item for item in dataset.reservations if item.id == cleaning.next_reservation_id)

    assert cleaning.scheduled_date == OPERATING_DATE
    assert cleaning.confirmation_status == ConfirmationStatus.CONFIRMED
    assert arrival.check_in_time.isoformat() == "15:00:00"


def test_beach_bungalow_has_unanswered_early_check_in_request(
    dataset: StayOpsDataset,
) -> None:
    message = next(item for item in dataset.guest_messages if item.id == "msg_beach_001")

    assert message.category == MessageCategory.EARLY_CHECK_IN
    assert message.requires_response is True
    assert message.responded_at is None


def test_vacant_properties_and_no_attention_property_are_represented(
    dataset: StayOpsDataset,
) -> None:
    occupied_property_ids = {
        reservation.property_id
        for reservation in dataset.reservations
        if reservation.check_in_date <= OPERATING_DATE < reservation.check_out_date
    }
    assert "prop_garden_cottage" not in occupied_property_ids
    assert "prop_mountain_retreat" not in occupied_property_ids

    sunset_unanswered = [
        message
        for message in dataset.guest_messages
        if message.property_id == "prop_sunset_house"
        and message.requires_response
        and message.responded_at is None
    ]
    sunset_open_tickets = [
        ticket
        for ticket in dataset.maintenance_tickets
        if ticket.property_id == "prop_sunset_house"
        and ticket.status != MaintenanceStatus.RESOLVED
    ]
    assert sunset_unanswered == []
    assert sunset_open_tickets == []


def test_cross_file_validation_rejects_broken_foreign_key() -> None:
    payload = {
        "properties": load_json("properties.json"),
        "reservations": load_json("reservations.json"),
        "guest_messages": load_json("guest_messages.json"),
        "cleaning_schedule": load_json("cleaning_schedule.json"),
        "maintenance_tickets": load_json("maintenance_tickets.json"),
        "property_rules": load_json("property_rules.json"),
    }
    payload["guest_messages"][0]["reservation_id"] = "res_missing"

    with pytest.raises(ValidationError, match="unknown reservation"):
        StayOpsDataset(**payload)
