from __future__ import annotations

from core.voice.config import VoiceSettings
from core.voice.language import resolve_language, resolve_response_language


def _settings(**overrides: object) -> VoiceSettings:
    defaults: dict[str, object] = dict(
        supported_languages=("ru", "uk", "en"),
        fallback_language="ru",
        language_confidence_threshold=0.6,
        response_language_override=None,
    )
    defaults.update(overrides)
    return VoiceSettings(**defaults)


def test_override_wins_over_detection_when_supported() -> None:
    decision = resolve_language("en", 0.99, _settings(), override="uk")

    assert decision.resolved == "uk"
    assert decision.source == "override"
    assert decision.detected == "en"


def test_override_is_ignored_when_not_supported() -> None:
    decision = resolve_language("en", 0.99, _settings(), override="fr")

    assert decision.source != "override"


def test_high_confidence_detection_is_used() -> None:
    decision = resolve_language("uk", 0.8, _settings())

    assert decision.resolved == "uk"
    assert decision.source == "detected"
    assert decision.confidence == 0.8


def test_low_confidence_detection_falls_back() -> None:
    decision = resolve_language("uk", 0.4, _settings())

    assert decision.resolved == "ru"
    assert decision.source == "fallback"
    assert decision.detected == "uk"


def test_unsupported_detected_language_falls_back() -> None:
    decision = resolve_language("fr", 0.99, _settings())

    assert decision.resolved == "ru"
    assert decision.source == "fallback"


def test_none_detected_language_falls_back() -> None:
    decision = resolve_language(None, 0.0, _settings())

    assert decision.resolved == "ru"
    assert decision.source == "fallback"
    assert decision.detected is None


def test_resolve_response_language_defaults_to_input_language() -> None:
    assert resolve_response_language("uk", _settings()) == "uk"


def test_resolve_response_language_override_always_wins() -> None:
    settings = _settings(response_language_override="en")

    assert resolve_response_language("uk", settings) == "en"
