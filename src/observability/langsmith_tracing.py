"""Opt-in LangSmith configuration and narrow read-tool tracing helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from langsmith import trace
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


ResultT = TypeVar("ResultT")
_READ_TOOL_CALLS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "stayops_read_tool_calls",
    default=None,
)


class LangSmithSettings(BaseModel):
    """Validate the environment used by the standalone trace runner."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_key: SecretStr | None = None
    project: str = Field(default="stayops-week4-eval", min_length=1)
    workspace_id: str | None = Field(default=None, min_length=1)
    endpoint: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def enabled_tracing_requires_api_key(self) -> LangSmithSettings:
        if self.enabled and self.api_key is None:
            raise ValueError(
                "LANGSMITH_API_KEY is required when LANGSMITH_TRACING=true"
            )
        return self

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> LangSmithSettings:
        env = os.environ if environment is None else environment
        api_key = env.get("LANGSMITH_API_KEY")
        workspace_id = env.get("LANGSMITH_WORKSPACE_ID")
        endpoint = env.get("LANGSMITH_ENDPOINT")
        return cls(
            enabled=env.get("LANGSMITH_TRACING", "false"),
            api_key=SecretStr(api_key) if api_key else None,
            project=env.get("LANGSMITH_PROJECT", "stayops-week4-eval"),
            workspace_id=workspace_id.strip() if workspace_id else None,
            endpoint=endpoint.strip() if endpoint else None,
        )


@contextmanager
def collect_read_tool_calls() -> Generator[list[dict[str, Any]], None, None]:
    """Collect actual read attempts without adding fields to graph state."""

    calls: list[dict[str, Any]] = []
    token = _READ_TOOL_CALLS.set(calls)
    try:
        yield calls
    finally:
        _READ_TOOL_CALLS.reset(token)


def _trace_output(result: Any) -> dict[str, Any]:
    items = getattr(result, "items", None)
    error = getattr(result, "error", None)
    code = getattr(error, "code", None)
    return {
        "success": bool(getattr(result, "success", False)),
        "record_count": len(items) if items is not None else 0,
        "error_code": getattr(code, "value", code),
    }


def trace_read_tool_call(
    tool_name: str,
    attempt: int,
    call: Callable[[], ResultT],
) -> ResultT:
    """Trace one existing read call without changing its inputs or result."""

    observed = _READ_TOOL_CALLS.get()
    if observed is not None:
        observed.append({"tool_name": tool_name, "attempt": attempt})

    with trace(
        tool_name,
        run_type="tool",
        inputs={"attempt": attempt},
        metadata={"component": "context_loader", "read_only": True},
    ) as run:
        result = call()
        run.end(outputs=_trace_output(result))
        return result
