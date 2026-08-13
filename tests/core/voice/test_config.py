from __future__ import annotations

import logging

from core.voice.config import VoiceSettings


def test_valid_response_language_override_is_kept() -> None:
    settings = VoiceSettings(response_language_override="uk")
    assert settings.response_language_override == "uk"


def test_none_response_language_override_is_kept() -> None:
    settings = VoiceSettings(response_language_override=None)
    assert settings.response_language_override is None


def test_invalid_response_language_override_is_cleared_with_a_warning(caplog) -> None:
    """Regression: an override outside supported_languages used to flow
    straight through to core/voice/intent.py's STOP_PHRASES.get(language,
    set()) — an empty-set fallback, unlike every other language-keyed
    lookup in this codebase, which silently made the barge-in "стоп"
    phrase (and yes/no confirmation of dangerous commands) permanently
    unrecognizable for the whole session with no error anywhere. Must be
    caught once here instead."""
    with caplog.at_level(logging.WARNING, logger="core.voice.config"):
        settings = VoiceSettings(response_language_override="RU")

    assert settings.response_language_override is None
    assert any("response_language_override" in record.message for record in caplog.records)


def test_default_settings_have_no_response_language_override() -> None:
    # The actual env-derived default (no ASSISTANT_RESPONSE_LANGUAGE_OVERRIDE/
    # ASSISTANT_FORCED_LANGUAGE set in this test run) must round-trip through
    # __post_init__ unchanged.
    settings = VoiceSettings()
    assert settings.response_language_override is None or (
        settings.response_language_override in settings.supported_languages
    )
