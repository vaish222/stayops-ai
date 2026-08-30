"""Typed boundaries for the optional StayOps voice interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceTranscription:
    """One confirmed speech-to-text result returned by a voice provider."""

    text: str
    language_code: str | None = None
    language_probability: float | None = None


class VoiceService(Protocol):
    """Provider-independent speech boundary used only by Ask StayOps."""

    @property
    def can_synthesize(self) -> bool: ...

    @property
    def output_mime_type(self) -> str: ...

    def transcribe(self, audio: bytes) -> VoiceTranscription: ...

    def synthesize(self, text: str) -> bytes: ...


class VoiceServiceError(RuntimeError):
    """Safe user-facing failure raised at the external voice boundary."""
