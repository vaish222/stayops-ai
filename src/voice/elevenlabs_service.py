"""ElevenLabs speech-to-text and text-to-speech adapter."""

from __future__ import annotations

import wave
from io import BytesIO
from typing import Any

from src.voice.contracts import (
    VoiceServiceError,
    VoiceTranscription,
)
from src.voice.settings import VoiceSettings


class ElevenLabsVoiceService:
    """Use ElevenLabs only as an interface around the existing StayOps graph."""

    def __init__(
        self,
        settings: VoiceSettings,
        *,
        client: Any | None = None,
    ) -> None:
        if not settings.enabled:
            raise ValueError("the ElevenLabs voice interface is disabled")
        if settings.api_key is None:
            raise ValueError("ElevenLabs voice configuration has no API key")
        if client is None:
            from elevenlabs.client import ElevenLabs

            client = ElevenLabs(
                api_key=settings.api_key.get_secret_value(),
            )
        self.settings = settings
        self.client = client

    @property
    def can_synthesize(self) -> bool:
        return self.settings.can_synthesize

    @property
    def output_mime_type(self) -> str:
        return self.settings.output_mime_type

    def _validate_audio(self, audio: bytes) -> None:
        if not audio:
            raise VoiceServiceError("Record a voice question before transcribing.")
        if len(audio) > self.settings.max_audio_bytes:
            raise VoiceServiceError(
                "The voice recording is too large. Record a shorter question."
            )
        try:
            with wave.open(BytesIO(audio), "rb") as recording:
                frame_rate = recording.getframerate()
                duration = (
                    recording.getnframes() / frame_rate
                    if frame_rate
                    else 0
                )
        except (EOFError, wave.Error):
            return
        if duration > self.settings.max_seconds:
            raise VoiceServiceError(
                f"Voice questions must be {self.settings.max_seconds:g} seconds or less."
            )

    def transcribe(self, audio: bytes) -> VoiceTranscription:
        self._validate_audio(audio)
        audio_file = BytesIO(audio)
        audio_file.name = "stayops-question.wav"
        try:
            result = self.client.speech_to_text.convert(
                file=audio_file,
                model_id=self.settings.stt_model,
                language_code=self.settings.language_code,
                diarize=False,
                tag_audio_events=False,
            )
        except Exception as exc:
            raise VoiceServiceError(
                "ElevenLabs could not transcribe the recording. Please try again."
            ) from exc
        text = str(getattr(result, "text", "")).strip()
        if not text:
            raise VoiceServiceError(
                "No speech was detected. Record the question again."
            )
        return VoiceTranscription(
            text=text,
            language_code=getattr(result, "language_code", None),
            language_probability=getattr(
                result,
                "language_probability",
                None,
            ),
        )

    def synthesize(self, text: str) -> bytes:
        normalized = text.strip()
        if not normalized:
            raise VoiceServiceError("There is no StayOps answer to read aloud.")
        if not self.settings.voice_id:
            raise VoiceServiceError(
                "Set ELEVENLABS_VOICE_ID to enable spoken answers."
            )
        try:
            response = self.client.text_to_speech.convert(
                text=normalized,
                voice_id=self.settings.voice_id,
                model_id=self.settings.tts_model,
                output_format=self.settings.output_format,
            )
            audio = (
                bytes(response)
                if isinstance(response, (bytes, bytearray))
                else b"".join(response)
            )
        except Exception as exc:
            raise VoiceServiceError(
                "ElevenLabs could not generate the spoken answer. Please try again."
            ) from exc
        if not audio:
            raise VoiceServiceError(
                "ElevenLabs returned an empty spoken answer. Please try again."
            )
        return audio
