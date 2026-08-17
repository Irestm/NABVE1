from __future__ import annotations

import numpy as np

from core.voice.tts_effects import (
    MAX_DELAY_SECONDS,
    MIN_DELAY_SECONDS,
    apply_response_delay,
    robotic_voice_effect,
    tunnel_voice_effect,
)

_SAMPLE_RATE = 16000


def _tone(seconds: float = 0.05) -> np.ndarray:
    t = np.arange(int(_SAMPLE_RATE * seconds), dtype=np.float32) / _SAMPLE_RATE
    return (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


def test_apply_response_delay_prepends_silence_of_the_requested_length() -> None:
    samples = _tone()

    out = apply_response_delay(samples, _SAMPLE_RATE, seconds=1.0)

    expected_silence = int(_SAMPLE_RATE * 1.0)
    assert out.shape[0] == expected_silence + samples.shape[0]
    assert np.all(out[:expected_silence] == 0.0)
    assert np.array_equal(out[expected_silence:], samples)


def test_apply_response_delay_clamps_below_the_minimum() -> None:
    samples = _tone()

    out = apply_response_delay(samples, _SAMPLE_RATE, seconds=0.0)

    assert out.shape[0] == int(_SAMPLE_RATE * MIN_DELAY_SECONDS) + samples.shape[0]


def test_apply_response_delay_clamps_above_the_maximum() -> None:
    samples = _tone()

    out = apply_response_delay(samples, _SAMPLE_RATE, seconds=999.0)

    assert out.shape[0] == int(_SAMPLE_RATE * MAX_DELAY_SECONDS) + samples.shape[0]


def test_apply_response_delay_is_a_no_op_for_invalid_sample_rate() -> None:
    samples = _tone()

    out = apply_response_delay(samples, 0, seconds=1.0)

    assert out is samples


def test_tunnel_voice_effect_preserves_shape_and_dtype_and_changes_the_signal() -> None:
    samples = _tone(0.2)

    out = tunnel_voice_effect(samples, _SAMPLE_RATE)

    assert out.shape == samples.shape
    assert out.dtype == np.float32
    assert not np.array_equal(out, samples)


def test_tunnel_voice_effect_handles_empty_input() -> None:
    empty = np.zeros(0, dtype=np.float32)

    assert tunnel_voice_effect(empty, _SAMPLE_RATE).shape == (0,)


def test_robotic_voice_effect_preserves_shape_and_dtype_and_changes_the_signal() -> None:
    samples = _tone(0.2)

    out = robotic_voice_effect(samples, _SAMPLE_RATE)

    assert out.shape == samples.shape
    assert out.dtype == np.float32
    assert not np.array_equal(out, samples)


def test_robotic_voice_effect_does_not_exceed_the_original_peak_amplitude() -> None:
    samples = _tone(0.2)

    out = robotic_voice_effect(samples, _SAMPLE_RATE)

    assert float(np.abs(out).max()) <= float(np.abs(samples).max()) + 1e-6


def test_robotic_voice_effect_handles_empty_input() -> None:
    empty = np.zeros(0, dtype=np.float32)

    assert robotic_voice_effect(empty, _SAMPLE_RATE).shape == (0,)
