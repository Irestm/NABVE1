from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    detected_language: str | None
    language_probability: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TranscriptionResult:
        return cls(
            text=str(raw.get("text", "")),
            detected_language=raw.get("detected_language"),
            language_probability=float(raw.get("language_probability", 0.0)),
        )


EMPTY_TRANSCRIPTION = TranscriptionResult(text="", detected_language=None, language_probability=0.0)
