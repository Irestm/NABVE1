from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.voice.config import VoiceSettings

LanguageSource = Literal["override", "detected", "fallback"]


@dataclass(frozen=True)
class LanguageDecision:
    resolved: str
    source: LanguageSource
    detected: str | None
    confidence: float


def resolve_language(
    detected_language: str | None,
    confidence: float,
    settings: VoiceSettings,
    *,
    override: str | None = None,
) -> LanguageDecision:
    """Resolve the language of the user's speech itself (used to interpret the
    command). Unaffected by `response_language_override`, which only controls
    the language of the assistant's spoken reply — see `resolve_response_language`.

    `override`, when given (e.g. from a UI language toggle), wins over
    auto-detection outright — this is also passed to Whisper itself so it
    decodes directly in that language instead of guessing, which is both
    faster and far more reliable than post-hoc confidence-gating a guess.
    """
    if override is not None and override in settings.supported_languages:
        return LanguageDecision(
            resolved=override,
            source="override",
            detected=detected_language,
            confidence=confidence,
        )

    if (
        detected_language is not None
        and detected_language in settings.supported_languages
        and confidence >= settings.language_confidence_threshold
    ):
        return LanguageDecision(
            resolved=detected_language,
            source="detected",
            detected=detected_language,
            confidence=confidence,
        )

    return LanguageDecision(
        resolved=settings.fallback_language,
        source="fallback",
        detected=detected_language,
        confidence=confidence,
    )


def resolve_response_language(input_language: str, settings: VoiceSettings) -> str:
    """Resolve the language the assistant should speak its reply in.

    Defaults to the language of the user's input (`input_language`, normally
    the `.resolved` field of a `resolve_language` result). If
    `response_language_override` is configured, it always wins.
    """
    if settings.response_language_override:
        return settings.response_language_override
    return input_language
