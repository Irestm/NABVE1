from __future__ import annotations

import numpy as np
import pytest

from core.voice.config import VoiceSettings
from core.voice.speech_gate import SpeechGate

_SAMPLE_RATE = 16000


def _gate(min_voiced_ratio: float = 0.05) -> SpeechGate:
    return SpeechGate(_SAMPLE_RATE, aggressiveness=2, min_voiced_ratio=min_voiced_ratio)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(_SAMPLE_RATE * seconds), dtype=np.float32)


def _voiced(seconds: float) -> np.ndarray:
    samples = int(_SAMPLE_RATE * seconds)
    time_axis = np.arange(samples, dtype=np.float32) / _SAMPLE_RATE
    harmonics = sum(np.sin(2 * np.pi * 140.0 * k * time_axis) / k for k in range(1, 12))
    noise = np.random.default_rng(1).standard_normal(samples) * 0.05
    return (0.25 * harmonics + noise).astype(np.float32)


def _window(total_seconds: float, speech_seconds: float) -> np.ndarray:
    lead = (total_seconds - speech_seconds) / 2
    return np.concatenate([_silence(lead), _voiced(speech_seconds), _silence(total_seconds - lead - speech_seconds)])


def test_silence_is_never_transcribed() -> None:
    assert _gate().should_transcribe(_silence(2.0)) is False


def test_faint_background_hiss_is_not_transcribed() -> None:
    hiss = (np.random.default_rng(2).standard_normal(_SAMPLE_RATE * 2) * 0.0005).astype(np.float32)

    assert _gate().should_transcribe(hiss) is False


def test_empty_and_sub_frame_windows_are_skipped() -> None:
    gate = _gate()

    assert gate.should_transcribe(np.zeros(0, dtype=np.float32)) is False
    assert gate.should_transcribe(np.ones(100, dtype=np.float32)) is False


@pytest.mark.parametrize(("window_seconds", "speech_seconds"), [(2.0, 0.3), (1.2, 0.25), (2.0, 1.5)])
def test_a_short_stop_word_still_opens_the_gate(window_seconds: float, speech_seconds: float) -> None:
    assert _gate().should_transcribe(_window(window_seconds, speech_seconds)) is True


def test_required_frames_scale_with_window_but_keep_a_floor() -> None:
    gate = _gate(0.05)

    assert gate.required_voiced_frames(66) == 4
    assert gate.required_voiced_frames(40) == 3
    assert gate.required_voiced_frames(10) == 3


def test_zero_ratio_disables_the_gate_for_non_empty_windows() -> None:
    gate = _gate(0.0)

    assert gate.should_transcribe(_silence(2.0)) is True
    assert gate.should_transcribe(np.zeros(0, dtype=np.float32)) is False


def test_gate_does_not_modify_the_caller_window_and_reuses_its_buffers() -> None:
    gate = _gate()
    window = _window(2.0, 0.5)
    original = window.copy()

    gate.should_transcribe(window)
    scratch = gate._scratch
    gate.should_transcribe(_window(2.0, 0.5))

    assert np.array_equal(window, original)
    assert gate._scratch is scratch


def test_gate_is_built_from_voice_settings() -> None:
    gate = SpeechGate.from_settings(VoiceSettings())

    assert gate.enabled is True
