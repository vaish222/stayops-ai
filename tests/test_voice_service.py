"""Provider-boundary tests for the optional ElevenLabs voice interface."""

from __future__ import annotations

import wave
from io import BytesIO
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.voice import (
    ElevenLabsVoiceService,
    VoiceServiceError,
    VoiceSettings,
)


def wav_recording(seconds: float, sample_rate: int = 16_000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buffer.getvalue()


class FakeSpeechToText:
    def __init__(self, text: str = "Who is checking in tomorrow?") -> None:
        self.text = text
        self.calls: list[dict] = []

    def convert(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            text=self.text,
            language_code="eng",
            language_probability=0.99,
        )


class FakeTextToSpeech:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def convert(self, **kwargs):
        self.calls.append(kwargs)
        return iter([b"first-", b"second"])


class FakeElevenLabsClient:
    def __init__(self, transcript: str = "Who is checking in tomorrow?") -> None:
        self.speech_to_text = FakeSpeechToText(transcript)
        self.text_to_speech = FakeTextToSpeech()


def enabled_settings(**overrides) -> VoiceSettings:
    values = {
        "enabled": True,
        "api_key": "test-key",
        "voice_id": "test-voice",
    }
    values.update(overrides)
    return VoiceSettings(**values)


def test_voice_settings_are_disabled_without_credentials_by_default() -> None:
    settings = VoiceSettings.from_environment({})

    assert settings.enabled is False
    assert settings.can_synthesize is False
    assert settings.stt_model == "scribe_v2"
    assert settings.tts_model == "eleven_flash_v2_5"


def test_enabled_voice_requires_elevenlabs_api_key() -> None:
    with pytest.raises(ValidationError, match="ELEVENLABS_API_KEY"):
        VoiceSettings.from_environment({"VOICE_ENABLED": "true"})


def test_settings_load_optional_tts_and_safety_limits() -> None:
    settings = VoiceSettings.from_environment(
        {
            "VOICE_ENABLED": "true",
            "ELEVENLABS_API_KEY": "secret",
            "ELEVENLABS_VOICE_ID": "voice-123",
            "VOICE_MAX_SECONDS": "20",
            "VOICE_MAX_AUDIO_BYTES": "500000",
        }
    )

    assert settings.can_synthesize is True
    assert settings.voice_id == "voice-123"
    assert settings.max_seconds == 20
    assert settings.max_audio_bytes == 500_000
    assert settings.api_key.get_secret_value() == "secret"


def test_elevenlabs_service_transcribes_streamlit_wav_recording() -> None:
    client = FakeElevenLabsClient()
    service = ElevenLabsVoiceService(enabled_settings(), client=client)

    result = service.transcribe(wav_recording(1))

    assert result.text == "Who is checking in tomorrow?"
    assert result.language_code == "eng"
    call = client.speech_to_text.calls[0]
    assert call["model_id"] == "scribe_v2"
    assert call["language_code"] == "eng"
    assert call["diarize"] is False
    assert call["tag_audio_events"] is False
    assert call["file"].name == "stayops-question.wav"


def test_elevenlabs_service_rejects_long_audio_before_provider_call() -> None:
    client = FakeElevenLabsClient()
    service = ElevenLabsVoiceService(
        enabled_settings(max_seconds=1),
        client=client,
    )

    with pytest.raises(VoiceServiceError, match="1 second"):
        service.transcribe(wav_recording(2))

    assert client.speech_to_text.calls == []


def test_elevenlabs_service_rejects_empty_transcript() -> None:
    service = ElevenLabsVoiceService(
        enabled_settings(),
        client=FakeElevenLabsClient("   "),
    )

    with pytest.raises(VoiceServiceError, match="No speech was detected"):
        service.transcribe(wav_recording(1))


def test_elevenlabs_service_generates_spoken_answer() -> None:
    client = FakeElevenLabsClient()
    service = ElevenLabsVoiceService(enabled_settings(), client=client)

    audio = service.synthesize("Two guests are checking in tomorrow.")

    assert audio == b"first-second"
    assert service.output_mime_type == "audio/mpeg"
    call = client.text_to_speech.calls[0]
    assert call == {
        "text": "Two guests are checking in tomorrow.",
        "voice_id": "test-voice",
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_44100_128",
    }


def test_tts_is_unavailable_without_a_configured_voice_id() -> None:
    service = ElevenLabsVoiceService(
        enabled_settings(voice_id=None),
        client=FakeElevenLabsClient(),
    )

    assert service.can_synthesize is False
    with pytest.raises(VoiceServiceError, match="ELEVENLABS_VOICE_ID"):
        service.synthesize("Answer")
