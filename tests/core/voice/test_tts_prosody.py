from __future__ import annotations

import numpy as np

from core.voice.tts import _apply_prosody_rate


def test_neutral_rate_is_a_no_op() -> None:
    samples = np.linspace(-1.0, 1.0, 100, dtype=np.float32)
    result = _apply_prosody_rate(samples, 1.0)
    assert result is samples


def test_empty_samples_are_returned_unchanged() -> None:
    samples = np.zeros(0, dtype=np.float32)
    result = _apply_prosody_rate(samples, 1.5)
    assert result.size == 0


def test_faster_rate_shortens_the_waveform() -> None:
    samples = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
    result = _apply_prosody_rate(samples, 1.25)
    assert result.size < samples.size


def test_slower_rate_lengthens_the_waveform() -> None:
    samples = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
    result = _apply_prosody_rate(samples, 0.8)
    assert result.size > samples.size


def test_output_dtype_is_float32() -> None:
    samples = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
    result = _apply_prosody_rate(samples, 1.15)
    assert result.dtype == np.float32
