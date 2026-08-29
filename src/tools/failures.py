"""Deterministic, opt-in failure simulation for retry and recovery tests."""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from src.tools.contracts import ReadToolName, ToolError, ToolErrorCode


class SimulatedFailureConfig(BaseModel):
    """Number of initial calls each read tool should fail before recovering."""

    model_config = ConfigDict(extra="forbid")

    failures_before_success: dict[
        ReadToolName,
        Annotated[int, Field(ge=0)],
    ] = Field(default_factory=dict)
    message: str = Field(
        default="Simulated transient read failure.",
        min_length=1,
    )


class FailureSimulator:
    """Thread-safe stateful failure plan shared across one or more tool calls."""

    def __init__(self, config: SimulatedFailureConfig | None = None) -> None:
        self.config = config or SimulatedFailureConfig()
        self._attempts: Counter[ReadToolName] = Counter()
        self._lock = Lock()

    def check(self, tool_name: ReadToolName) -> ToolError | None:
        """Record an attempt and return an error while its failure budget remains."""

        with self._lock:
            self._attempts[tool_name] += 1
            attempt = self._attempts[tool_name]
            failure_budget = self.config.failures_before_success.get(tool_name, 0)

        if attempt > failure_budget:
            return None
        return ToolError(
            code=ToolErrorCode.SIMULATED_FAILURE,
            message=self.config.message,
            tool_name=tool_name,
            retryable=True,
            details={"attempt": attempt, "failures_before_success": failure_budget},
        )

    def attempt_count(self, tool_name: ReadToolName) -> int:
        """Return how often a tool has checked this simulator."""

        with self._lock:
            return self._attempts[tool_name]

    def reset(self) -> None:
        """Reset all attempt counters while preserving the configured plan."""

        with self._lock:
            self._attempts.clear()
