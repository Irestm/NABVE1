from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pytest

from core.voice import audio_io
from core.voice.vad import SpeechActivityDetector

_SAMPLE_RATE = 16000
_FRAME_SAMPLES = SpeechActivityDetector(_SAMPLE_RATE).frame_samples


def _silence_frame() -> np.ndarray:
    return np.zeros(_FRAME_SAMPLES, dtype=np.float32)


def _speech_frame() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.standard_normal(_FRAME_SAMPLES) * 0.3).astype(np.float32)


class _FakeStream:
    def __init__(self, chunks: list[np.ndarray]) -> None:
        self._chunks = list(chunks)

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        chunk = self._chunks.pop(0) if self._chunks else _silence_frame()
        return chunk.reshape(-1, 1), False


@dataclass
class _FakeSoundDevice:
    chunks: list[np.ndarray]
    last_stream: _FakeStream = field(default=None)  # type: ignore[assignment]

    def InputStream(self, samplerate: int, channels: int, dtype: str, latency: str | None = None) -> _FakeStream:
        self.last_stream = _FakeStream(self.chunks)
        return self.last_stream


def _settings(**overrides: object) -> SimpleNamespace:
    defaults = dict(
        sample_rate=_SAMPLE_RATE,
        command_silence_timeout_seconds=0.09,  # 3 frames at 30ms
        command_max_seconds=0.3,  # 10 frames hard cap
        vad_aggressiveness=2,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_stops_after_speech_followed_by_enough_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    # Generous trailing silence and a hard cap well beyond what's needed, so
    # the silence-timeout stop is clearly distinguishable from the
    # command_max_seconds cap: webrtcvad is a stateful streaming detector
    # with a short "hangover" after speech, so a frame or two of true
    # silence right after speech can still classify as speech — the trailing
    # run needs enough frames to outlast that before the timeout can fire.
    chunks = [_silence_frame(), _silence_frame()] + [_speech_frame()] * 2 + [_silence_frame()] * 20
    fake_sd = _FakeSoundDevice(chunks)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)

    result = audio_io.record_until_silence(_settings(command_max_seconds=0.9), threading.Event())

    assert _FRAME_SAMPLES * 2 <= result.shape[0] < _FRAME_SAMPLES * 30


def test_leading_silence_before_any_speech_never_triggers_a_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the original bug: silence before the user has
    said anything must never by itself satisfy the stop timeout — only
    silence *after* real speech should."""
    chunks = [_silence_frame()] * 20  # never any speech at all
    fake_sd = _FakeSoundDevice(chunks)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)

    result = audio_io.record_until_silence(_settings(), threading.Event())

    # Recording must run all the way to the command_max_seconds hard cap
    # (10 frames), not stop early on leading silence.
    assert result.shape[0] == _FRAME_SAMPLES * 10


def test_stop_event_interrupts_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sd = _FakeSoundDevice([_speech_frame()] * 50)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)

    stop_event = threading.Event()
    stop_event.set()

    result = audio_io.record_until_silence(_settings(), stop_event)

    assert result.shape[0] == 0


def test_onset_timeout_gives_up_when_no_speech_ever_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_silence_frame()] * 20  # never any speech at all
    fake_sd = _FakeSoundDevice(chunks)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)

    result = audio_io.record_until_silence(
        _settings(), threading.Event(), onset_timeout_seconds=0.09  # 3 frames
    )

    assert result.shape[0] == 0


def test_onset_timeout_does_not_cut_off_speech_that_already_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Speech starts right away, before the onset timeout would even fire —
    # onset_timeout_seconds only guards "nothing said at all," never an
    # already-started utterance that happens to run past that same duration.
    chunks = [_speech_frame()] * 2 + [_silence_frame()] * 20
    fake_sd = _FakeSoundDevice(chunks)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)

    result = audio_io.record_until_silence(
        _settings(command_max_seconds=0.9), threading.Event(), onset_timeout_seconds=0.03  # 1 frame
    )

    assert result.shape[0] > 0


class _FakeCallbackStream:
    def __init__(
        self,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
        callback: object,
        fail_on_start: bool,
        latency: str | None = None,
    ) -> None:
        self.callback = callback
        self.started = False
        self.closed = False
        self.stopped = False
        self._fail_on_start = fail_on_start

    def start(self) -> None:
        if self._fail_on_start:
            raise RuntimeError("device busy")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeSoundDeviceForBuffer:
    fail_on_start: bool = False
    last_stream: _FakeCallbackStream = field(default=None)  # type: ignore[assignment]

    def InputStream(self, **kwargs: object) -> _FakeCallbackStream:
        self.last_stream = _FakeCallbackStream(fail_on_start=self.fail_on_start, **kwargs)
        return self.last_stream


def test_rolling_audio_buffer_closes_the_stream_if_start_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: InputStream's constructor already opens the PortAudio
    # handle before .start() is even called — a failure in .start() used to
    # leave that handle assigned to self._stream with nothing ever closing
    # it, since the assignment happened before the call that could raise.
    fake_sd = _FakeSoundDeviceForBuffer(fail_on_start=True)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)
    buffer = audio_io.RollingAudioBuffer(_settings())

    with pytest.raises(RuntimeError):
        buffer.start()

    assert fake_sd.last_stream is not None
    assert fake_sd.last_stream.closed is True
    assert buffer._stream is None


def test_rolling_audio_buffer_start_and_stop_succeed_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sd = _FakeSoundDeviceForBuffer(fail_on_start=False)
    monkeypatch.setattr(audio_io, "require_sounddevice", lambda: fake_sd)
    buffer = audio_io.RollingAudioBuffer(_settings())

    buffer.start()

    assert fake_sd.last_stream.started is True
    assert buffer._stream is fake_sd.last_stream

    buffer.stop()

    assert fake_sd.last_stream.stopped is True
    assert fake_sd.last_stream.closed is True
    assert buffer._stream is None
