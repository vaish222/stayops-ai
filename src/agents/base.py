"""Shared LangChain runnable wrapper and evidence-safe helper functions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Generic, TypeVar

from langchain_core.runnables import Runnable, RunnableLambda

from src.models import (
    AgentWarning,
    FindingSeverity,
    SpecialistFinding,
    SpecialistInput,
    SpecialistName,
    SpecialistOutput,
)


InputT = TypeVar("InputT", bound=SpecialistInput)

SEVERITY_RANK = {
    FindingSeverity.LOW: 0,
    FindingSeverity.MEDIUM: 1,
    FindingSeverity.HIGH: 2,
    FindingSeverity.CRITICAL: 3,
}


def date_in_scope(value: date, start: date | None, end: date | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def property_in_scope(property_id: str, property_scope: list[str]) -> bool:
    return not property_scope or property_id in property_scope


def severity_at_least(
    severity: FindingSeverity,
    minimum: FindingSeverity,
) -> FindingSeverity:
    return minimum if SEVERITY_RANK[severity] < SEVERITY_RANK[minimum] else severity


def sort_findings(findings: list[SpecialistFinding]) -> list[SpecialistFinding]:
    return sorted(
        findings,
        key=lambda finding: (
            -SEVERITY_RANK[finding.severity],
            finding.property_id,
            finding.finding_id,
        ),
    )


class BaseSpecialistAgent(ABC, Generic[InputT]):
    """A typed LangChain runnable that can only analyze supplied input records."""

    input_model: type[InputT]
    specialist: SpecialistName

    def __init__(self) -> None:
        self.runnable: Runnable[InputT | dict[str, Any], SpecialistOutput] = (
            RunnableLambda(
                self._run_validated,
                name=f"{self.specialist.value}_specialist_agent",
            ).with_types(
                input_type=self.input_model,
                output_type=SpecialistOutput,
            )
        )

    def invoke(self, payload: InputT | dict[str, Any]) -> SpecialistOutput:
        """Invoke this specialist synchronously through its LangChain runnable."""

        result = self.runnable.invoke(payload)
        return SpecialistOutput.model_validate(result)

    def _run_validated(self, payload: InputT | dict[str, Any]) -> SpecialistOutput:
        context = (
            payload
            if isinstance(payload, self.input_model)
            else self.input_model.model_validate(payload)
        )
        return SpecialistOutput.model_validate(self.analyze(context))

    @abstractmethod
    def analyze(self, context: InputT) -> SpecialistOutput:
        """Analyze supplied records without performing operational writes."""

    def build_output(
        self,
        context: InputT,
        findings: list[SpecialistFinding],
        analyzed_record_ids: list[str],
    ) -> SpecialistOutput:
        warnings = [
            AgentWarning(
                code=error.code,
                message=error.message,
                source_tool=error.tool_name,
                retryable=error.retryable,
            )
            for error in context.source_errors
        ]
        return SpecialistOutput(
            specialist=self.specialist,
            findings=sort_findings(findings),
            analyzed_record_ids=list(dict.fromkeys(analyzed_record_ids)),
            warnings=warnings,
        )

    @staticmethod
    def failed_source_tools(context: InputT) -> set[str]:
        return {error.tool_name for error in context.source_errors}

