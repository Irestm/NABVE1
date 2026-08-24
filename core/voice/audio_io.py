from __future__ import annotations

import queue
import threading
from types import ModuleType

import numpy as np

from core.logger import get_logger
from core.voice.config import VoiceSettings
from core.voice.vad import SpeechActivityDetector

logger = get_logger(__name__)


def require_sounddevice() -> ModuleType:
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "No audio backend available (PortAudio). Install system audio libraries "
            "and ensure a microphone/speaker device is present."
        ) from exc
    return sounddevice


def record_until_silence(
    settings: VoiceSettings,
    stop_event: threading.Event,
    *,
    onset_timeout_seconds: float | None = None,
) -> np.ndarray:
    """Records until the user stops talking, or `command_max_seconds` is
    hit as a hard cap. "Stopped talking" is judged with real voice-activity
    detection (core/voice/vad.py) rather than a raw energy threshold, and —
    critically — silence is only counted *after* speech has actually been
    heard at least once: without that, a quiet moment right after the wake
    word (before the user has said anything) could itself satisfy the
    silence timeout and cut the recording short before it began. This
    combination is what fixes the assistant answering before the user
    finished speaking.

    `onset_timeout_seconds`, if given, additionally gives up — returning an
    empty array — if no speech has been detected at all within that many
    seconds, rather than only the much longer `command_max_seconds` hard
    cap (90s by default: a ceiling against a runaway mic for a command
    that's already started, not a short "is anyone even talking" check).
    Used by core/voice/pipeline.py's post-answer follow-up window (see
    VoiceAssistantLoop._maybe_continue_free_text), where silence is the
    expected, common case — most answers don't get a follow-up — so
    waiting a full 90 seconds before giving up on every single turn would
    make the assistant feel stuck instead of quietly returning to
    wake-word listening."""
    sd = require_sounddevice()
    vad = SpeechActivityDetector(settings.sample_rate, settings.vad_aggressiveness)
    frame_seconds = vad.frame_samples / settings.sample_rate

    frames: list[np.ndarray] = []
    silence_seconds = 0.0
    elapsed_seconds = 0.0
    speech_detected = False

    with sd.InputStream(
        samplerate=settings.sample_rate, channels=1, dtype="float32", latency="low"
    ) as stream:
        while (
            elapsed_seconds < settings.command_max_seconds
            and not stop_event.is_set()
        ):
            if (
                onset_timeout_seconds is not None
                and not speech_detected
                and elapsed_seconds >= onset_timeout_seconds
            ):
                return np.zeros(0, dtype=np.float32)

            chunk, _overflowed = stream.read(vad.frame_samples)
            chunk = chunk.reshape(-1)
            frames.append(chunk)
            elapsed_seconds += frame_seconds

            if vad.is_speech(chunk):
                speech_detected = True
                silence_seconds = 0.0
                continue

            if not speech_detected:
                # Silence before the user has said anything yet — waiting,
                # not counting down to a stop.
                continue

            silence_seconds += frame_seconds
            if silence_seconds >= settings.command_silence_timeout_seconds:
                break

    if not frames:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(frames)


def play_audio(samples: np.ndarray, sample_rate: int, stop_event: threading.Event | None = None) -> None:
    """Plays `samples`, blocking until playback finishes — or, if `stop_event`
    is given and gets set while playing (see core/voice/barge_in.py), aborts
    immediately instead of waiting for the reply to finish, for voice
    barge-in ("stop" while the assistant is talking)."""
    if samples.size == 0:
        return
    sd = require_sounddevice()
    sd.play(samples, samplerate=sample_rate)
    if stop_event is None:
        sd.wait()
        return

    poll_seconds = 0.05
    stream = sd.get_stream()
    while stream is not None and stream.active:
        if stop_event.wait(poll_seconds):
            sd.stop()
            return


class RollingAudioBuffer:
    def __init__(self, settings: VoiceSettings, window_seconds: float = 2.0) -> None:
        self._settings = settings
        self._window_seconds = window_seconds
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: object | None = None

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
        if status:
            logger.debug("Audio input status: %s", status)
        self._queue.put(indata.copy().reshape(-1))

    def start(self) -> None:
        sd = require_sounddevice()
        stream = sd.InputStream(
            samplerate=self._settings.sample_rate,
            channels=1,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        # Only assign to self._stream once .start() has actually succeeded —
        # InputStream's constructor already opens the PortAudio handle, so a
        # failure here (device busy, unplugged, ...) still needs the handle
        # closed instead of leaked; a caller catching this exception never
        # gets a chance to call stop() on a stream that was never assigned.
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()  # type: ignore[attr-defined]
            self._stream.close()  # type: ignore[attr-defined]
            self._stream = None

    def read_window(self, timeout: float) -> np.ndarray:
        window_frames = int(self._settings.sample_rate * self._window_seconds)
        chunks: list[np.ndarray] = []
        collected = 0
        try:
            while collected < window_frames:
                chunk = self._queue.get(timeout=timeout)
                chunks.append(chunk)
                collected += chunk.shape[0]
        except queue.Empty:
            pass
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)[-window_frames:]
