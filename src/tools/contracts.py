"""Typed success and error contracts shared by all read tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadToolName(StrEnum):
    GET_PROPERTIES = "get_properties"
    GET_PROPERTY_RULES = "get_property_rules"
    GET_RESERVATIONS = "get_reservations"
    GET_GUEST_MESSAGES = "get_guest_messages"
    GET_CLEANING_SCHEDULE = "get_cleaning_schedule"
    GET_MAINTENANCE_TICKETS = "get_maintenance_tickets"


class ToolErrorCode(StrEnum):
    INVALID_FILTER = "invalid_filter"
    DATA_UNAVAILABLE = "data_unavailable"
    INVALID_DATA = "invalid_data"
    SIMULATED_FAILURE = "simulated_failure"


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    message: str = Field(min_length=1)
    tool_name: ReadToolName
    retryable: bool
    details: dict[str, str | int | bool] = Field(default_factory=dict)


class ToolMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: ReadToolName
    returned_count: int = Field(ge=0)
    filters: dict[str, str | list[str] | None] = Field(default_factory=dict)


RecordT = TypeVar("RecordT")


class ReadResult(BaseModel, Generic[RecordT]):
    """A non-throwing tool response with typed records or a structured error."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    items: list[RecordT] = Field(default_factory=list)
    metadata: ToolMetadata
    error: ToolError | None = None

    @model_validator(mode="after")
    def state_must_be_consistent(self) -> ReadResult[RecordT]:
        if self.success and self.error is not None:
            raise ValueError("successful results cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("failed results must contain an error")
        if not self.success and self.items:
            raise ValueError("failed results cannot contain records")
        if self.metadata.returned_count != len(self.items):
            raise ValueError("returned_count must match the number of items")
        return self
