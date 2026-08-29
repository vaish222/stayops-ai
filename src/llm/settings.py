"""Validated environment settings for the optional LLM synthesizer."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class SynthesizerMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"


class LLMProvider(StrEnum):
    NEBIUS = "nebius"
    OLLAMA = "ollama"


class LLMSynthesizerFallback(StrEnum):
    DETERMINISTIC = "deterministic"
    DISABLED = "disabled"


class SynthesizerSettings(BaseModel):
    """Configuration that validates provider requirements only in LLM mode."""

    model_config = ConfigDict(extra="forbid")

    mode: SynthesizerMode = SynthesizerMode.DETERMINISTIC
    provider: LLMProvider | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: SecretStr | None = None
    base_url: str | None = Field(default=None, min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    fallback: LLMSynthesizerFallback = LLMSynthesizerFallback.DETERMINISTIC

    @model_validator(mode="after")
    def llm_mode_must_be_configured(self) -> SynthesizerSettings:
        if self.mode == SynthesizerMode.DETERMINISTIC:
            return self
        if self.provider is None:
            raise ValueError("LLM_PROVIDER is required when SYNTHESIZER_MODE=llm")
        if self.model is None:
            raise ValueError("LLM_MODEL is required when SYNTHESIZER_MODE=llm")
        if self.provider == LLMProvider.NEBIUS and self.api_key is None:
            raise ValueError(
                "NEBIUS_API_KEY or LLM_API_KEY is required for the Nebius provider"
            )
        if self.base_url is None:
            raise ValueError("an LLM provider base URL is required in LLM mode")
        return self

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> SynthesizerSettings:
        env = os.environ if environment is None else environment
        mode = SynthesizerMode(env.get("SYNTHESIZER_MODE", "deterministic").casefold())
        provider_value = env.get("LLM_PROVIDER")
        provider = LLMProvider(provider_value.casefold()) if provider_value else None
        if provider == LLMProvider.NEBIUS:
            base_url = env.get(
                "LLM_BASE_URL",
                "https://api.tokenfactory.nebius.com/v1/",
            )
            api_key = env.get("NEBIUS_API_KEY") or env.get("LLM_API_KEY")
        elif provider == LLMProvider.OLLAMA:
            base_url = env.get("OLLAMA_BASE_URL", "http://localhost:11434")
            api_key = None
        else:
            base_url = env.get("LLM_BASE_URL")
            api_key = env.get("LLM_API_KEY")
        return cls(
            mode=mode,
            provider=provider,
            model=env.get("LLM_MODEL"),
            api_key=SecretStr(api_key) if api_key else None,
            base_url=base_url,
            timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "30")),
            fallback=LLMSynthesizerFallback(
                env.get("LLM_SYNTHESIZER_FALLBACK", "deterministic").casefold()
            ),
        )
