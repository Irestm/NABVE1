from __future__ import annotations

import threading

import numpy as np
import pytest

import core.voice.barge_in as barge_in_module
from core.voice.barge_in import BargeInMonitor
from core.voice.config import VoiceSettings
from core.voice.stt import TranscriptionResult


class _FakeBuffer:
    """Stands in for RollingAudioBuffer: yields a fixed sequence of
    "windows" (each just a marker int, since BargeInMonitor never inspects
    window contents itself — only whether it's empty) to the monitor loop,
    then an empty array forever after, so a test that doesn't itself stop
    the monitor still terminates instead of spinning."""

    def __init__(self, windows: list[np.ndarray], start_error: Exception | None = None) -> None:
        self._windows = iter(windows)
        self._start_error = start_error
        self.started = False
        self.stopped = False

    def start(self) -> None:
        if self._start_error is not None:
            raise self._start_error
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def read_window(self, timeout: float) -> np.ndarray:
        return next(self._windows, np.zeros(0, dtype=np.float32))


def _monitor(
    monkeypatch,
    buffer: _FakeBuffer,
    transcriptions: list[TranscriptionResult | Exception],
    *,
    stop_word: str | None = "стоп",
) -> BargeInMonitor:
    monkeypatch.setattr(barge_in_module, "RollingAudioBuffer", lambda settings, window_seconds: buffer)
    monkeypatch.setattr(
        barge_in_module.special_phrases.profile_service_layer,
        "get_fact",
        lambda uow, key: stop_word,
    )
    monitor = BargeInMonitor(VoiceSettings())

    results = iter(transcriptions)

    def fake_transcribe(window, language):
        outcome = next(results, TranscriptionResult(text="", detected_language="ru", language_probability=0.9))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(monitor._stt, "transcribe", fake_transcribe)
    return monitor


def _non_empty_window() -> np.ndarray:
    return np.ones(1, dtype=np.float32)


def test_stop_phrase_sets_interrupted_and_stop_event(monkeypatch) -> None:
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [TranscriptionResult(text="стоп", detected_language="ru", language_probability=0.95)],
    )

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)

    assert interrupted.is_set()
    assert stop_event.is_set()
    assert buffer.stopped  # mic released regardless of how the loop ends


def test_fuzzy_stop_phrase_variant_is_still_recognized(monkeypatch) -> None:
    """special_phrases.check is fuzzy (core/voice/phrase_matching.py), not
    exact — a slightly-off transcription of the configured stop word, or
    one buried among a couple of extra words, must still interrupt."""
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [TranscriptionResult(text="хватит уже", detected_language="ru", language_probability=0.9)],
        stop_word="хватит",
    )

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)

    assert interrupted.is_set()


def test_ordinary_speech_does_not_trigger_a_false_interrupt(monkeypatch) -> None:
    buffer = _FakeBuffer([_non_empty_window(), _non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [
            TranscriptionResult(text="какая сегодня погода", detected_language="ru", language_probability=0.9),
            TranscriptionResult(text="", detected_language="ru", language_probability=0.9),
        ],
    )

    stop_event = threading.Event()
    interrupted = threading.Event()

    # Nothing in this fake buffer ever matches a stop phrase, so the loop
    # would spin forever reading empty windows once the fixed sequence is
    # exhausted — stop it externally after giving it a moment to run, the
    # same way playback finishing normally does in the real flow.
    def stop_soon() -> None:
        stop_event.set()

    timer = threading.Timer(0.05, stop_soon)
    timer.start()
    try:
        monitor.run("ru", stop_event, interrupted)
    finally:
        timer.cancel()

    assert not interrupted.is_set()
    assert stop_event.is_set()  # set externally, not by the monitor itself


def test_transcription_failure_is_swallowed_and_does_not_crash(monkeypatch) -> None:
    """A single bad window's transcription failing must not kill the
    monitor thread for the rest of the reply — see barge_in.py's own
    except Exception around the transcribe call."""
    buffer = _FakeBuffer([_non_empty_window(), _non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [
            RuntimeError("simulated STT crash"),
            TranscriptionResult(text="стоп", detected_language="ru", language_probability=0.9),
        ],
    )

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)  # must not raise

    assert interrupted.is_set()  # recovered and caught the stop phrase on the next window


def test_no_configured_stop_word_means_nothing_can_interrupt(monkeypatch) -> None:
    """Regression: barge-in used to always recognize a fixed built-in word
    list (STOP_PHRASES/is_stop_command) regardless of profile configuration.
    Now it checks only the user's own configured stop word (see
    core/voice/special_phrases.py) - with none set, even a bare "стоп" must
    not interrupt."""
    buffer = _FakeBuffer([_non_empty_window(), _non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [
            TranscriptionResult(text="стоп", detected_language="ru", language_probability=0.95),
            TranscriptionResult(text="", detected_language="ru", language_probability=0.9),
        ],
        stop_word=None,
    )

    stop_event = threading.Event()
    interrupted = threading.Event()

    def stop_soon() -> None:
        stop_event.set()

    timer = threading.Timer(0.05, stop_soon)
    timer.start()
    try:
        monitor.run("ru", stop_event, interrupted)
    finally:
        timer.cancel()

    assert not interrupted.is_set()


def test_context_defaults_to_speaking_but_forwards_a_custom_one(monkeypatch) -> None:
    # BargeInMonitor is reused to bracket the user's own command recording
    # too (context="recording" — see core/voice/pipeline.py's
    # _record_command_audio), not just TTS playback ("speaking", the
    # default). special_phrases.check must see whichever one was passed.
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [TranscriptionResult(text="стоп", detected_language="ru", language_probability=0.9)],
    )

    seen_contexts: list[str] = []
    real_check = barge_in_module.special_phrases.check

    def spying_check(text, context, settings):
        seen_contexts.append(context)
        return real_check(text, context, settings)

    monkeypatch.setattr(barge_in_module.special_phrases, "check", spying_check)

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted, context="recording")

    assert interrupted.is_set()
    assert seen_contexts == ["recording"]


def test_custom_stop_word_not_in_the_old_fixed_list_still_interrupts(monkeypatch) -> None:
    """The flip side of the above: a stop word the user picked themselves,
    which was never one of the old fixed STOP_PHRASES entries, must work."""
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [TranscriptionResult(text="орел", detected_language="ru", language_probability=0.9)],
        stop_word="орел",
    )

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)

    assert interrupted.is_set()


def test_mic_unavailable_degrades_to_no_interruption_instead_of_raising(monkeypatch) -> None:
    buffer = _FakeBuffer([], start_error=RuntimeError("no audio backend"))
    monitor = _monitor(monkeypatch, buffer, [])

    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)  # must not raise

    assert not interrupted.is_set()
    assert not stop_event.is_set()  # the caller's own stop_event is untouched, not force-set


def test_stop_event_already_set_before_start_exits_immediately(monkeypatch) -> None:
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(monkeypatch, buffer, [])

    stop_event = threading.Event()
    stop_event.set()
    interrupted = threading.Event()
    monitor.run("ru", stop_event, interrupted)

    assert not interrupted.is_set()
    assert buffer.stopped


def test_response_language_override_outside_supported_languages_is_rejected_before_reaching_here() -> None:
    """Documents WHY BargeInMonitor never needs to defend against an
    unrecognized `language` itself: core/voice/config.py's
    VoiceSettings.__post_init__ already clears an invalid
    response_language_override before it can ever reach
    self._stt.transcribe(window, language) — special_phrases.check's own
    matching is language-agnostic (a plain text fuzzy match against the
    configured stop word), so only the transcription call itself would be
    at risk from a bad language code. See tests/core/voice/test_config.py
    for that guarantee directly."""
    settings = VoiceSettings(response_language_override="not-a-real-language")
    assert settings.response_language_override is None
