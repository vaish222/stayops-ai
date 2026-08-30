"""Optional speech interface for Ask StayOps."""

from src.voice.contracts import (
    VoiceService,
    VoiceServiceError,
    VoiceTranscription,
)
from src.voice.elevenlabs_service import ElevenLabsVoiceService
from src.voice.settings import VoiceSettings

__all__ = [
    "ElevenLabsVoiceService",
    "VoiceService",
    "VoiceServiceError",
    "VoiceSettings",
    "VoiceTranscription",
]
