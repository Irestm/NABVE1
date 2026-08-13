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


def _monitor(monkeypatch, buffer: _FakeBuffer, transcriptions: list[TranscriptionResult | Exception]) -> BargeInMonitor:
    monkeypatch.setattr(barge_in_module, "RollingAudioBuffer", lambda settings, window_seconds: buffer)
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
    """is_stop_command is fuzzy (core/voice/intent.py), not exact — a
    slightly-off transcription of a real stop word must still interrupt."""
    buffer = _FakeBuffer([_non_empty_window()])
    monitor = _monitor(
        monkeypatch,
        buffer,
        [TranscriptionResult(text="хватит уже", detected_language="ru", language_probability=0.9)],
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
    response_language_override before it can ever reach is_stop_command's
    STOP_PHRASES.get(language, set()) (which has no fallback — an
    unrecognized language means the stop phrase can never match at all,
    silently). See tests/core/voice/test_config.py for that guarantee
    directly."""
    settings = VoiceSettings(response_language_override="not-a-real-language")
    assert settings.response_language_override is None
