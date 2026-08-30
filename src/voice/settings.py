"""Environment-backed configuration for the optional ElevenLabs voice layer."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class VoiceSettings(BaseModel):
    """Validate voice configuration only when the interface is enabled."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_key: SecretStr | None = None
    stt_model: str = Field(default="scribe_v2", min_length=1)
    tts_model: str = Field(default="eleven_flash_v2_5", min_length=1)
    voice_id: str | None = Field(default=None, min_length=1)
    output_format: str = Field(default="mp3_44100_128", min_length=1)
    language_code: str | None = Field(default="eng", min_length=2)
    max_seconds: float = Field(default=30.0, gt=0, le=300)
    max_audio_bytes: int = Field(default=10_000_000, gt=0)

    @model_validator(mode="after")
    def enabled_voice_requires_api_key(self) -> VoiceSettings:
        if self.enabled and self.api_key is None:
            raise ValueError(
                "ELEVENLABS_API_KEY is required when VOICE_ENABLED=true"
            )
        return self

    @property
    def can_synthesize(self) -> bool:
        return self.enabled and self.voice_id is not None

    @property
    def output_mime_type(self) -> str:
        return (
            "audio/mpeg"
            if self.output_format.startswith("mp3_")
            else "audio/wav"
            if self.output_format.startswith("wav_")
            else "audio/pcm"
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> VoiceSettings:
        env = os.environ if environment is None else environment
        api_key = env.get("ELEVENLABS_API_KEY")
        language_code = env.get("ELEVENLABS_LANGUAGE_CODE", "eng").strip()
        voice_id = env.get("ELEVENLABS_VOICE_ID")
        return cls(
            enabled=env.get("VOICE_ENABLED", "false"),
            api_key=SecretStr(api_key) if api_key else None,
            stt_model=env.get("ELEVENLABS_STT_MODEL", "scribe_v2"),
            tts_model=env.get(
                "ELEVENLABS_TTS_MODEL",
                "eleven_flash_v2_5",
            ),
            voice_id=voice_id.strip() if voice_id else None,
            output_format=env.get(
                "ELEVENLABS_OUTPUT_FORMAT",
                "mp3_44100_128",
            ),
            language_code=language_code or None,
            max_seconds=float(env.get("VOICE_MAX_SECONDS", "30")),
            max_audio_bytes=int(
                env.get("VOICE_MAX_AUDIO_BYTES", "10000000")
            ),
        )
