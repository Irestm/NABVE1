from __future__ import annotations

import core.voice.special_phrases as special_phrases
from core.voice.config import VoiceSettings
from modules.tray_hide.config import HIDE_PHRASE_KEY, SHOW_PHRASE_KEY
from modules.user_profile.domain import STOP_WORD_KEY, WAKE_PHRASE_KEY


def _mock_facts(
    monkeypatch,
    *,
    stop_word: str | None = None,
    hide_phrase: str | None = None,
    show_phrase: str | None = None,
    wake_phrase: str | None = None,
) -> None:
    values = {
        STOP_WORD_KEY: stop_word,
        HIDE_PHRASE_KEY: hide_phrase,
        SHOW_PHRASE_KEY: show_phrase,
        WAKE_PHRASE_KEY: wake_phrase,
    }
    monkeypatch.setattr(special_phrases.profile_service_layer, "get_fact", lambda uow, key: values.get(key))


# --- variants_for_context ----------------------------------------------------


def test_idle_context_omits_pause_without_a_configured_stop_word(monkeypatch) -> None:
    _mock_facts(monkeypatch)
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "idle")

    assert "pause" not in phrases
    assert "wake" in phrases
    assert "tray_hide" in phrases
    assert "tray_show" in phrases


def test_idle_context_includes_pause_before_wake_when_stop_word_configured(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "idle")

    assert list(phrases.keys())[0] == "pause"  # must win a same-utterance race against "wake"
    assert phrases["pause"] == ("стоп", "stop")  # with_transliterated_variant's Latin fallback


def test_paused_context_only_offers_resume(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "paused")

    assert phrases == {"resume": ("стоп", "stop")}


def test_paused_context_is_empty_without_a_configured_stop_word(monkeypatch) -> None:
    _mock_facts(monkeypatch)
    settings = VoiceSettings()

    assert special_phrases.variants_for_context(settings, "paused") == {}


def test_speaking_context_only_offers_pause(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "speaking")

    assert phrases == {"pause": ("стоп", "stop")}


def test_recording_context_only_offers_pause(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "recording")

    assert phrases == {"pause": ("стоп", "stop")}


def test_custom_wake_and_tray_phrases_are_folded_in_alongside_defaults(monkeypatch) -> None:
    _mock_facts(monkeypatch, wake_phrase="джарвис проснись", hide_phrase="исчезни", show_phrase="явись")
    settings = VoiceSettings()

    phrases = special_phrases.variants_for_context(settings, "idle")

    assert "джарвис проснись" in phrases["wake"]
    assert "исчезни" in phrases["tray_hide"]
    assert "явись" in phrases["tray_show"]


# --- check --------------------------------------------------------------------


def test_check_matches_configured_stop_word_in_speaking_context(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    assert special_phrases.check("стоп", "speaking", settings) == "pause"


def test_check_ignores_unconfigured_stop_word_in_speaking_context(monkeypatch) -> None:
    _mock_facts(monkeypatch)
    settings = VoiceSettings()

    assert special_phrases.check("стоп", "speaking", settings) is None


def test_check_does_not_match_wake_phrase_in_speaking_context(monkeypatch) -> None:
    # "wake" is only valid in the "idle" context - even a perfect wake-phrase
    # utterance must not match anything while the assistant is speaking.
    _mock_facts(monkeypatch)
    settings = VoiceSettings()

    assert special_phrases.check("привет", "speaking", settings) is None


def test_check_returns_none_for_unrelated_text(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    assert special_phrases.check("какая сегодня погода", "speaking", settings) is None


def test_check_matches_configured_stop_word_in_recording_context(monkeypatch) -> None:
    _mock_facts(monkeypatch, stop_word="стоп")
    settings = VoiceSettings()

    assert special_phrases.check("стоп", "recording", settings) == "pause"
