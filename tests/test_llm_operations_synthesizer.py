"""Grounding, fallback, and configuration tests for optional LLM synthesis."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.agents.llm_operations_synthesizer import (
    LLMOperationsSynthesizer,
    LLMSynthesisUnavailable,
)
from src.graph import build_phase_6_graph, create_initial_state
from src.llm.factory import build_synthesis_runner
from src.llm.settings import (
    LLMProvider,
    LLMSynthesizerFallback,
    SynthesizerMode,
    SynthesizerSettings,
)
from src.models import (
    EvidenceSource,
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    OverallStatus,
    ReviewReasonCode,
    SpecialistFinding,
    SpecialistName,
    SynthesisInvocation,
    WriteToolName,
)


class FakeStructuredModel:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> Any:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.response


def finding(
    finding_id: str,
    *,
    property_id: str = "prop_lake_house",
    specialist: SpecialistName = SpecialistName.TURNOVER,
    category: FindingCategory = FindingCategory.SAME_DAY_TURNOVER,
    severity: FindingSeverity = FindingSeverity.HIGH,
    source: EvidenceSource = EvidenceSource.RESERVATIONS,
    record_id: str = "res_lake_001",
    requires_attention: bool = True,
    recommended_action: str | None = "Review this supported issue.",
) -> SpecialistFinding:
    return SpecialistFinding(
        finding_id=finding_id,
        specialist=specialist,
        property_id=property_id,
        category=category,
        severity=severity,
        summary=f"Supported {category.value} issue.",
        evidence=[
            FindingEvidence(
                source=source,
                record_ids=[record_id],
                fact=f"Supported evidence for {record_id} on 2026-08-29 at 14:00.",
            )
        ],
        recommended_next_action=recommended_action,
        requires_attention=requires_attention,
    )


def llm_runner(
    response: Any = None,
    *,
    error: Exception | None = None,
    provider: LLMProvider = LLMProvider.NEBIUS,
    fallback: LLMSynthesizerFallback = LLMSynthesizerFallback.DETERMINISTIC,
) -> tuple[LLMOperationsSynthesizer, FakeStructuredModel]:
    model = FakeStructuredModel(response=response, error=error)
    return (
        LLMOperationsSynthesizer(
            structured_model=model,
            provider=provider,
            model="test-model",
            fallback=fallback,
        ),
        model,
    )


def test_llm_groups_and_prioritizes_while_python_grounds_actions() -> None:
    same_day = finding("turnover:same-day:lake")
    confirmation = finding(
        "turnover:confirmation:lake",
        category=FindingCategory.CLEANER_CONFIRMATION_MISSING,
        source=EvidenceSource.CLEANING_SCHEDULE,
        record_id="clean_lake_001",
    )
    runner, model = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 1,
                    "source_finding_ids": [
                        same_day.finding_id,
                        confirmation.finding_id,
                    ],
                    "summary": (
                        "Same-day turnover on 2026-08-29 is missing cleaner "
                        "confirmation for clean_lake_001."
                    ),
                }
            ],
        }
    )

    result = runner.invoke(
        SynthesisInvocation(
            specialist_findings=[same_day, confirmation],
            property_scope=["prop_lake_house"],
            date_scope="2026-08-29",
        )
    )

    assert result.metadata.status == "completed"
    assert result.metadata.provider == "nebius"
    assert result.output.overall_status == OverallStatus.NEEDS_ATTENTION
    prioritized = result.output.prioritized_findings[0]
    assert prioritized.source_finding_ids == [
        same_day.finding_id,
        confirmation.finding_id,
    ]
    assert len(prioritized.evidence) == 2
    action = result.output.proposed_actions[0]
    assert action.tool_name == WriteToolName.SEND_CLEANER_MESSAGE
    assert action.target_record_id == "clean_lake_001"
    assert action.description == (
        "Please confirm whether the scheduled turnover will be completed "
        "by the target time."
    )
    assert len(model.calls) == 1


def test_llm_can_prioritize_multiple_properties_without_cross_property_grouping() -> None:
    lake = finding("turnover:lake")
    city = finding(
        "maintenance:city",
        property_id="prop_city_loft",
        specialist=SpecialistName.MAINTENANCE,
        category=FindingCategory.OPEN_MAINTENANCE,
        severity=FindingSeverity.MEDIUM,
        source=EvidenceSource.MAINTENANCE_TICKETS,
        record_id="maint_city_001",
    )
    runner, _ = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 1,
                    "source_finding_ids": [lake.finding_id],
                    "summary": "Lake turnover needs attention.",
                },
                {
                    "priority_rank": 2,
                    "source_finding_ids": [city.finding_id],
                    "summary": "City maintenance needs follow-up.",
                },
            ],
        }
    )

    result = runner.invoke(
        SynthesisInvocation(
            specialist_findings=[city, lake],
            property_scope=["prop_lake_house", "prop_city_loft"],
        )
    )

    assert [item.property_id for item in result.output.prioritized_findings] == [
        "prop_lake_house",
        "prop_city_loft",
    ]


def test_llm_links_guest_maintenance_report_to_supported_ticket() -> None:
    guest = finding(
        "guest:maintenance:lake",
        specialist=SpecialistName.GUEST,
        category=FindingCategory.GUEST_MAINTENANCE_REPORT,
        source=EvidenceSource.GUEST_MESSAGES,
        record_id="msg_lake_001",
    )
    maintenance = finding(
        "maintenance:open:lake",
        specialist=SpecialistName.MAINTENANCE,
        category=FindingCategory.GUEST_IMPACTING_MAINTENANCE,
        source=EvidenceSource.MAINTENANCE_TICKETS,
        record_id="maint_lake_001",
    )
    runner, _ = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 1,
                    "source_finding_ids": [guest.finding_id, maintenance.finding_id],
                    "summary": (
                        "The guest maintenance report and maintenance ticket "
                        "describe one supported issue."
                    ),
                }
            ],
        }
    )

    result = runner.invoke(
        SynthesisInvocation(specialist_findings=[guest, maintenance])
    )

    prioritized = result.output.prioritized_findings[0]
    assert prioritized.specialist_sources == [
        SpecialistName.GUEST,
        SpecialistName.MAINTENANCE,
    ]
    assert {item.source for item in prioritized.evidence} == {
        EvidenceSource.GUEST_MESSAGES,
        EvidenceSource.MAINTENANCE_TICKETS,
    }
    assert result.output.proposed_actions[0].tool_name == (
        WriteToolName.SEND_GUEST_MESSAGE
    )


def test_conflicting_findings_must_remain_explicitly_uncertain() -> None:
    on_track = finding(
        "turnover:on-track:lake",
        category=FindingCategory.TURNOVER_ON_TRACK,
        severity=FindingSeverity.LOW,
        source=EvidenceSource.CLEANING_SCHEDULE,
        record_id="clean_lake_001",
        requires_attention=False,
        recommended_action=None,
    )
    missing = finding(
        "turnover:missing:lake",
        category=FindingCategory.CLEANER_CONFIRMATION_MISSING,
        source=EvidenceSource.CLEANING_SCHEDULE,
        record_id="clean_lake_001",
    )
    runner, _ = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 1,
                    "source_finding_ids": [on_track.finding_id, missing.finding_id],
                    "summary": "The cleaner status conflicts and needs verification.",
                }
            ],
        }
    )

    result = runner.invoke(
        SynthesisInvocation(specialist_findings=[on_track, missing])
    )

    assert "conflicts" in result.output.prioritized_findings[0].summary


def test_hallucinated_reference_uses_deterministic_fallback() -> None:
    source = finding("turnover:lake")
    runner, _ = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 1,
                    "source_finding_ids": [source.finding_id],
                    "summary": "Reservation res_invented_999 needs attention.",
                }
            ],
        }
    )

    result = runner.invoke(SynthesisInvocation(specialist_findings=[source]))

    assert result.metadata.status == "fallback"
    assert result.metadata.error_code == "llm_grounding_failure"
    assert result.output.prioritized_findings[0].summary == source.summary


def test_malformed_structured_output_uses_deterministic_fallback() -> None:
    source = finding("turnover:lake")
    runner, _ = llm_runner(
        {
            "overall_status": "needs_attention",
            "prioritized_findings": [
                {
                    "priority_rank": 7,
                    "source_finding_ids": [source.finding_id],
                    "summary": "Supported turnover issue.",
                }
            ],
        }
    )

    result = runner.invoke(SynthesisInvocation(specialist_findings=[source]))

    assert result.metadata.status == "fallback"
    assert result.metadata.error_code == "llm_schema_validation_failure"


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_provider_failure_falls_back_without_exposing_credentials(
    provider: LLMProvider,
) -> None:
    runner, _ = llm_runner(
        error=ConnectionError("provider unavailable"),
        provider=provider,
    )

    result = runner.invoke(
        SynthesisInvocation(specialist_findings=[finding("turnover:lake")])
    )

    serialized = result.metadata.model_dump_json()
    assert result.metadata.status == "fallback"
    assert result.metadata.error_code == "llm_provider_failure"
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_failure_without_fallback_returns_safe_failed_metadata() -> None:
    runner, _ = llm_runner(
        error=TimeoutError("provider timeout"),
        fallback=LLMSynthesizerFallback.DISABLED,
    )

    with pytest.raises(LLMSynthesisUnavailable) as error:
        runner.invoke(
            SynthesisInvocation(specialist_findings=[finding("turnover:lake")])
        )

    assert error.value.metadata.status == "failed"
    assert error.value.metadata.fallback_used is False
    assert "provider timeout" not in str(error.value)


def test_empty_findings_produce_a_grounded_no_findings_result() -> None:
    runner, _ = llm_runner(
        {"overall_status": "no_findings", "prioritized_findings": []}
    )

    result = runner.invoke(SynthesisInvocation(specialist_findings=[]))

    assert result.output.overall_status == OverallStatus.NO_FINDINGS
    assert result.output.prioritized_findings == []
    assert result.output.proposed_actions == []


def test_default_settings_keep_deterministic_synthesis() -> None:
    settings = SynthesizerSettings.from_environment({})
    runner = build_synthesis_runner(settings)

    assert settings.mode == SynthesizerMode.DETERMINISTIC
    result = runner.invoke(SynthesisInvocation(specialist_findings=[]))
    assert result.metadata.mode == "deterministic"


def test_nebius_and_ollama_settings_are_provider_neutral() -> None:
    nebius = SynthesizerSettings.from_environment(
        {
            "SYNTHESIZER_MODE": "llm",
            "LLM_PROVIDER": "nebius",
            "LLM_MODEL": "provider-model",
            "NEBIUS_API_KEY": "private-value",
        }
    )
    ollama = SynthesizerSettings.from_environment(
        {
            "SYNTHESIZER_MODE": "llm",
            "LLM_PROVIDER": "ollama",
            "LLM_MODEL": "local-model",
        }
    )

    assert nebius.base_url == "https://api.tokenfactory.nebius.com/v1/"
    assert nebius.api_key is not None
    assert nebius.api_key.get_secret_value() == "private-value"
    assert ollama.base_url == "http://localhost:11434"
    assert ollama.api_key is None


def test_nebius_never_uses_an_openai_api_key_as_its_credential() -> None:
    with pytest.raises(ValidationError, match="NEBIUS_API_KEY or LLM_API_KEY"):
        SynthesizerSettings.from_environment(
            {
                "SYNTHESIZER_MODE": "llm",
                "LLM_PROVIDER": "nebius",
                "LLM_MODEL": "provider-model",
                "OPENAI_API_KEY": "must-not-be-used",
            }
        )


def test_graph_reports_warning_when_llm_fails_and_fallback_is_disabled() -> None:
    runner, _ = llm_runner(
        error=ConnectionError("down"),
        fallback=LLMSynthesizerFallback.DISABLED,
    )
    graph = build_phase_6_graph(synthesis_runner=runner)

    result = graph.invoke(create_initial_state("What needs attention today?"))

    assert result["analysis_complete"] is False
    assert result["synthesis_complete"] is False
    assert result["synthesis_run"]["status"] == "failed"
    assert result["requires_human_review"] is False
    assert ReviewReasonCode.SYNTHESIS_UNAVAILABLE.value in {
        warning["code"] for warning in result["operational_warnings"]
    }
