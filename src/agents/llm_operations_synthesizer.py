"""Optional, evidence-bounded LLM synthesis with deterministic assembly."""

from __future__ import annotations

import json
import re
from time import perf_counter_ns
from typing import Any, Protocol

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from src.agents.operations_synthesizer import OperationsSynthesizer
from src.llm.settings import LLMProvider, LLMSynthesizerFallback
from src.models import (
    FindingCategory,
    LLMSynthesisDraft,
    OperationsSynthesisInput,
    OperationsSynthesisOutput,
    OverallStatus,
    SpecialistFinding,
    SynthesisExecutionResult,
    SynthesisInvocation,
    SynthesisRunMetadata,
    SynthesisRunStatus,
)


SYSTEM_PROMPT = """You are the Operations Synthesizer for StayOps AI.

Use only the supplied structured specialist findings. Group related findings and
rank them using current guest impact, upcoming check-in risk, operational
urgency, severity, and timing. Every output item must cite all and only the
specialist finding IDs that support it. Cover every supplied finding exactly
once. Never add a property, guest, reservation, date, time, cleaner,
maintenance detail, or record ID that is absent from the supplied findings.
Keep conflicting findings visibly uncertain instead of resolving them by
assumption. Do not create tools, actions, approvals, or execution instructions.
Return only data matching the supplied schema.
"""


CONFLICTING_CATEGORY_PAIRS = {
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANER_CONFIRMATION_MISSING,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANER_DECLINED,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.TURNOVER_TIMING_RISK,
        }
    ),
    frozenset(
        {
            FindingCategory.TURNOVER_ON_TRACK,
            FindingCategory.CLEANING_SCHEDULE_MISSING,
        }
    ),
}
FACT_REFERENCE_PATTERN = re.compile(
    r"\b(?:prop|res|msg|clean|maint|rule)_[a-zA-Z0-9_]+\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b"
)


class StructuredSynthesisModel(Protocol):
    def invoke(self, messages: list[Any]) -> Any: ...


class SynthesisGroundingError(ValueError):
    """Raised when structured output cannot be traced to supplied findings."""


class LLMSynthesisUnavailable(RuntimeError):
    """Carries safe metadata when LLM synthesis fails without fallback."""

    def __init__(self, metadata: SynthesisRunMetadata) -> None:
        super().__init__("LLM synthesis is unavailable and fallback is disabled")
        self.metadata = metadata


def _elapsed_ms(started_at: int) -> float:
    return round((perf_counter_ns() - started_at) / 1_000_000, 3)


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, SynthesisGroundingError):
        return "llm_grounding_failure"
    if isinstance(exc, (ValidationError, OutputParserException)):
        return "llm_schema_validation_failure"
    return "llm_provider_failure"


class DeterministicSynthesisRunner:
    """Adapt the unchanged deterministic synthesizer to the graph invocation."""

    def __init__(self, delegate: OperationsSynthesizer | None = None) -> None:
        self.delegate = delegate or OperationsSynthesizer()

    def invoke(
        self,
        payload: SynthesisInvocation | dict[str, Any],
    ) -> SynthesisExecutionResult:
        started_at = perf_counter_ns()
        context = (
            payload
            if isinstance(payload, SynthesisInvocation)
            else SynthesisInvocation.model_validate(payload)
        )
        output = self.delegate.invoke(
            OperationsSynthesisInput(
                specialist_findings=context.specialist_findings,
            )
        )
        return SynthesisExecutionResult(
            output=output,
            metadata=SynthesisRunMetadata(
                mode="deterministic",
                status=SynthesisRunStatus.COMPLETED,
                latency_ms=_elapsed_ms(started_at),
                prioritized_finding_count=len(output.prioritized_findings),
            ),
        )


class LLMOperationsSynthesizer:
    """Let an LLM group/rank findings, then assemble all safety fields in Python."""

    def __init__(
        self,
        *,
        structured_model: StructuredSynthesisModel,
        provider: LLMProvider,
        model: str,
        fallback: LLMSynthesizerFallback,
        deterministic: OperationsSynthesizer | None = None,
    ) -> None:
        self.structured_model = structured_model
        self.provider = provider
        self.model = model
        self.fallback = fallback
        self.deterministic = deterministic or OperationsSynthesizer()

    def invoke(
        self,
        payload: SynthesisInvocation | dict[str, Any],
    ) -> SynthesisExecutionResult:
        started_at = perf_counter_ns()
        context = (
            payload
            if isinstance(payload, SynthesisInvocation)
            else SynthesisInvocation.model_validate(payload)
        )
        try:
            draft = self._invoke_llm(context)
            output = self._assemble_grounded_output(context, draft)
        except Exception as exc:
            code = _failure_code(exc)
            if self.fallback == LLMSynthesizerFallback.DETERMINISTIC:
                output = self.deterministic.invoke(
                    OperationsSynthesisInput(
                        specialist_findings=context.specialist_findings,
                    )
                )
                return SynthesisExecutionResult(
                    output=output,
                    metadata=SynthesisRunMetadata(
                        mode="llm",
                        provider=self.provider.value,
                        model=self.model,
                        status=SynthesisRunStatus.FALLBACK,
                        latency_ms=_elapsed_ms(started_at),
                        prioritized_finding_count=len(output.prioritized_findings),
                        fallback_used=True,
                        error_code=code,
                        error_type=type(exc).__name__,
                    ),
                )
            raise LLMSynthesisUnavailable(
                SynthesisRunMetadata(
                    mode="llm",
                    provider=self.provider.value,
                    model=self.model,
                    status=SynthesisRunStatus.FAILED,
                    latency_ms=_elapsed_ms(started_at),
                    prioritized_finding_count=0,
                    fallback_used=False,
                    error_code=code,
                    error_type=type(exc).__name__,
                )
            ) from exc

        return SynthesisExecutionResult(
            output=output,
            metadata=SynthesisRunMetadata(
                mode="llm",
                provider=self.provider.value,
                model=self.model,
                status=SynthesisRunStatus.COMPLETED,
                latency_ms=_elapsed_ms(started_at),
                prioritized_finding_count=len(output.prioritized_findings),
            ),
        )

    def _invoke_llm(self, context: SynthesisInvocation) -> LLMSynthesisDraft:
        payload = {
            "property_scope": context.property_scope,
            "date_scope": context.date_scope,
            "specialist_findings": [
                finding.model_dump(mode="json")
                for finding in context.specialist_findings
            ],
            "specialist_errors": context.specialist_errors,
        }
        result = self.structured_model.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, sort_keys=True)),
            ]
        )
        return LLMSynthesisDraft.model_validate(result)

    def _assemble_grounded_output(
        self,
        context: SynthesisInvocation,
        draft: LLMSynthesisDraft,
    ) -> OperationsSynthesisOutput:
        source_by_id = {
            finding.finding_id: finding for finding in context.specialist_findings
        }
        supplied_ids = set(source_by_id)
        used_ids = [
            finding_id
            for draft_finding in draft.prioritized_findings
            for finding_id in draft_finding.source_finding_ids
        ]
        if set(used_ids) != supplied_ids or len(used_ids) != len(set(used_ids)):
            raise SynthesisGroundingError(
                "LLM output must cover every supplied finding exactly once"
            )

        prioritized = []
        for item in draft.prioritized_findings:
            contributors = [
                source_by_id[finding_id]
                for finding_id in item.source_finding_ids
            ]
            property_ids = {finding.property_id for finding in contributors}
            if len(property_ids) != 1:
                raise SynthesisGroundingError(
                    "one prioritized issue cannot combine findings from different properties"
                )
            if context.property_scope and not property_ids.issubset(
                context.property_scope
            ):
                raise SynthesisGroundingError(
                    "LLM output is outside the routed property scope"
                )
            self._validate_generated_references(item.summary, contributors)
            if self._contains_conflict(contributors) and not any(
                term in item.summary.casefold()
                for term in ("conflict", "uncertain", "verify", "disagree")
            ):
                raise SynthesisGroundingError(
                    "conflicting findings must preserve uncertainty in the summary"
                )
            prioritized.append(
                self.deterministic.build_grounded_finding(
                    contributors,
                    summary=item.summary,
                    priority_rank=item.priority_rank,
                )
            )

        output = self.deterministic.assemble_prioritized_findings(prioritized)
        if output.overall_status != draft.overall_status:
            raise SynthesisGroundingError(
                "LLM overall status does not match evidence-derived severity"
            )
        return output

    @staticmethod
    def _validate_generated_references(
        summary: str,
        contributors: list[SpecialistFinding],
    ) -> None:
        source_text = json.dumps(
            [finding.model_dump(mode="json") for finding in contributors],
            sort_keys=True,
        )
        unsupported = [
            reference
            for reference in FACT_REFERENCE_PATTERN.findall(summary)
            if reference not in source_text
        ]
        if unsupported:
            raise SynthesisGroundingError(
                "LLM summary contains references absent from supporting evidence"
            )

    @staticmethod
    def _contains_conflict(findings: list[SpecialistFinding]) -> bool:
        for index, left in enumerate(findings):
            left_ids = {
                record_id
                for evidence in left.evidence
                for record_id in evidence.record_ids
            }
            for right in findings[index + 1 :]:
                if (
                    frozenset({left.category, right.category})
                    not in CONFLICTING_CATEGORY_PAIRS
                ):
                    continue
                right_ids = {
                    record_id
                    for evidence in right.evidence
                    for record_id in evidence.record_ids
                }
                if left_ids.intersection(right_ids):
                    return True
        return False
