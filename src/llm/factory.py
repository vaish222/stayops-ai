"""Isolate provider-specific model construction from graph orchestration."""

from __future__ import annotations

from typing import Any

from src.agents.llm_operations_synthesizer import (
    DeterministicSynthesisRunner,
    LLMOperationsSynthesizer,
)
from src.llm.settings import LLMProvider, SynthesizerMode, SynthesizerSettings
from src.models import LLMSynthesisDraft


def get_chat_model(settings: SynthesizerSettings) -> Any:
    """Construct only the configured provider; never read OpenAI credentials."""

    if settings.mode != SynthesizerMode.LLM or settings.provider is None:
        raise ValueError("a chat model can only be created for configured LLM mode")
    if settings.provider == LLMProvider.NEBIUS:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key.get_secret_value() if settings.api_key else None,
            base_url=settings.base_url,
            temperature=0,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )
    if settings.provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.model,
            base_url=settings.base_url,
            temperature=0,
            client_kwargs={"timeout": settings.timeout_seconds},
        )
    raise ValueError(f"unsupported LLM provider: {settings.provider}")


def build_synthesis_runner(
    settings: SynthesizerSettings | None = None,
    *,
    structured_model: Any | None = None,
):
    """Build the selected implementation behind one graph-facing interface."""

    configured = settings or SynthesizerSettings.from_environment()
    if configured.mode == SynthesizerMode.DETERMINISTIC:
        return DeterministicSynthesisRunner()
    assert configured.provider is not None
    assert configured.model is not None
    model = structured_model
    if model is None:
        chat_model = get_chat_model(configured)
        model = chat_model.with_structured_output(
            LLMSynthesisDraft,
            method="json_schema",
        )
    return LLMOperationsSynthesizer(
        structured_model=model,
        provider=configured.provider,
        model=configured.model,
        fallback=configured.fallback,
    )
