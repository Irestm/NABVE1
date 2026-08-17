from __future__ import annotations

import threading

import numpy as np

import core.voice.wake_word as wake_word_module
from core.voice.config import VoiceSettings
from core.voice.stt import TranscriptionResult


class _FakeSTT:
    def __init__(self, model_size: str) -> None:
        self.model_size = model_size

    def transcribe(self, window, language=None):
        raise AssertionError("not used in these tests; _listen_for_any is stubbed out")


def setup_function() -> None:
    # Module-level cache (see wake_word._phrase_stt_by_size) persists across
    # tests otherwise, letting an earlier test's instances leak into a later
    # one's assertions.
    wake_word_module._phrase_stt_by_size.clear()


def test_defaults_to_wake_tier_when_model_size_not_given(monkeypatch) -> None:
    settings = VoiceSettings()
    seen: list[str] = []
    monkeypatch.setattr(
        wake_word_module,
        "SpeechToText",
        lambda settings, model_size: seen.append(model_size) or _FakeSTT(model_size),
    )
    monkeypatch.setattr(wake_word_module, "_listen_for_any", lambda stt, settings, phrases, stop_event: "wake")

    result = wake_word_module.listen_for_phrases(settings, {"wake": settings.wake_word}, threading.Event())

    assert result == "wake"
    assert seen == [settings.whisper_wake_model_size]


def test_explicit_model_size_overrides_wake_tier_default(monkeypatch) -> None:
    settings = VoiceSettings()
    seen: list[str] = []
    monkeypatch.setattr(
        wake_word_module,
        "SpeechToText",
        lambda settings, model_size: seen.append(model_size) or _FakeSTT(model_size),
    )
    monkeypatch.setattr(wake_word_module, "_listen_for_any", lambda stt, settings, phrases, stop_event: "pause")

    result = wake_word_module.listen_for_phrases(
        settings, {"pause": "стоп"}, threading.Event(), model_size=settings.whisper_model_size
    )

    assert result == "pause"
    assert seen == [settings.whisper_model_size]


def test_caches_one_instance_per_model_size(monkeypatch) -> None:
    settings = VoiceSettings()
    construction_count = {"n": 0}

    def fake_speech_to_text(settings, model_size):
        construction_count["n"] += 1
        return _FakeSTT(model_size)

    monkeypatch.setattr(wake_word_module, "SpeechToText", fake_speech_to_text)
    monkeypatch.setattr(wake_word_module, "_listen_for_any", lambda stt, settings, phrases, stop_event: "wake")

    wake_word_module.listen_for_phrases(settings, {"wake": "x"}, threading.Event(), model_size="tiny")
    wake_word_module.listen_for_phrases(settings, {"wake": "x"}, threading.Event(), model_size="tiny")
    wake_word_module.listen_for_phrases(settings, {"wake": "x"}, threading.Event(), model_size="base")

    assert construction_count["n"] == 2  # one for "tiny", one for "base" - "tiny" reused on the second call


# --- _listen_for_any pins the transcription language -----------------------
# Regression: a short 1-2 word window (exactly what a wake word or a
# one-word stop word usually is) gave Whisper's own per-window language
# autodetect too little to go on, and it routinely misclassified it as a
# different language - a stop word saved as "нос" came back transcribed as
# "NOS"/"¡Nos!" (detected as English/Spanish) often enough that
# fuzzy_contains_phrase, which has no notion of cross-alphabet equivalence,
# could never match it against the stored Cyrillic phrase. This was measured
# directly via a real TTS->STT round trip against the actual configured
# stop word before being fixed, not assumed.


class _RecordingSTT:
    def __init__(self, reply_text: str) -> None:
        self.calls: list[str | None] = []
        self._reply_text = reply_text

    def transcribe(self, window, language=None) -> TranscriptionResult:
        self.calls.append(language)
        return TranscriptionResult(text=self._reply_text, detected_language=language, language_probability=0.99)


def test_listen_for_any_pins_language_to_fallback_language(monkeypatch) -> None:
    settings = VoiceSettings()
    stt = _RecordingSTT("нос")

    windows = iter([np.ones(1, dtype=np.float32), np.zeros(0, dtype=np.float32)])
    monkeypatch.setattr(
        wake_word_module.RollingAudioBuffer,
        "read_window",
        lambda self, timeout: next(windows, np.zeros(0, dtype=np.float32)),
    )
    monkeypatch.setattr(wake_word_module.RollingAudioBuffer, "start", lambda self: None)
    monkeypatch.setattr(wake_word_module.RollingAudioBuffer, "stop", lambda self: None)

    stop_event = threading.Event()
    result = wake_word_module._listen_for_any(stt, settings, {"pause": "нос"}, stop_event)

    assert result == "pause"
    assert stt.calls == [settings.fallback_language]


def test_listen_for_any_matches_any_variant_in_a_phrase_tuple(monkeypatch) -> None:
    # modules/tray_hide passes a tuple of interchangeable phrases (defaults
    # plus an optional custom one) under a single name - any one of them
    # heard should count as that name matching.
    settings = VoiceSettings()
    stt = _RecordingSTT("скройся")

    windows = iter([np.ones(1, dtype=np.float32), np.zeros(0, dtype=np.float32)])
    monkeypatch.setattr(
        wake_word_module.RollingAudioBuffer,
        "read_window",
        lambda self, timeout: next(windows, np.zeros(0, dtype=np.float32)),
    )
    monkeypatch.setattr(wake_word_module.RollingAudioBuffer, "start", lambda self: None)
    monkeypatch.setattr(wake_word_module.RollingAudioBuffer, "stop", lambda self: None)

    stop_event = threading.Event()
    result = wake_word_module._listen_for_any(
        stt, settings, {"tray_hide": ("спрячься", "скройся", "уйди в трей")}, stop_event
    )

    assert result == "tray_hide"


# --- resolve_wake_phrases ----------------------------------------------------


def test_resolve_wake_phrases_returns_defaults_plus_settings_wake_word_when_no_custom_phrase() -> None:
    settings = VoiceSettings()

    phrases = wake_word_module.resolve_wake_phrases(settings, None)

    assert set(wake_word_module.DEFAULT_WAKE_PHRASES) <= set(phrases)
    assert settings.wake_word in phrases


def test_resolve_wake_phrases_adds_custom_phrase_without_dropping_defaults() -> None:
    settings = VoiceSettings()

    phrases = wake_word_module.resolve_wake_phrases(settings, "джарвис проснись")

    assert "джарвис проснись" in phrases
    assert set(wake_word_module.DEFAULT_WAKE_PHRASES) <= set(phrases)


def test_resolve_wake_phrases_deduplicates_case_and_whitespace_insensitively() -> None:
    settings = VoiceSettings()

    phrases = wake_word_module.resolve_wake_phrases(settings, "  Привет  ")

    assert phrases.count("привет") + phrases.count("Привет") + phrases.count("  Привет  ") == 1


def test_resolve_wake_phrases_ignores_blank_custom_phrase() -> None:
    settings = VoiceSettings()

    phrases = wake_word_module.resolve_wake_phrases(settings, "   ")

    assert phrases == wake_word_module.resolve_wake_phrases(settings, None)
