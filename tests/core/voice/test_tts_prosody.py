from __future__ import annotations

import numpy as np

from core.voice.tts import _apply_pitch_shift, _apply_prosody_rate, _time_stretch

_SR = 48000


def _tone(freq: float, seconds: float = 1.0, sample_rate: int = _SR) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _dominant_freq(samples: np.ndarray, sample_rate: int = _SR) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(samples.size)))
    freqs = np.fft.rfftfreq(samples.size, 1.0 / sample_rate)
    return float(freqs[int(np.argmax(spectrum))])


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


def test_slower_rate_keeps_the_pitch() -> None:
    tone = _tone(220.0)
    slowed = _apply_prosody_rate(tone, 0.8, _SR)
    assert slowed.size > tone.size
    assert abs(_dominant_freq(slowed) - 220.0) < 8.0
    assert np.isfinite(slowed).all()


def test_faster_rate_keeps_the_pitch() -> None:
    tone = _tone(220.0)
    sped = _apply_prosody_rate(tone, 1.25, _SR)
    assert sped.size < tone.size
    assert abs(_dominant_freq(sped) - 220.0) < 8.0


def test_time_stretch_preserves_energy_roughly() -> None:
    tone = _tone(180.0)
    stretched = _time_stretch(tone, _SR, 1.3)
    rms_in = float(np.sqrt(np.mean(tone**2)))
    rms_out = float(np.sqrt(np.mean(stretched**2)))
    assert 0.5 * rms_in < rms_out < 1.6 * rms_in


def test_pitch_shift_lowers_frequency_and_keeps_duration() -> None:
    tone = _tone(300.0)
    deep = _apply_pitch_shift(tone, _SR, 0.5)
    assert abs(deep.size - tone.size) < 0.1 * tone.size
    assert abs(_dominant_freq(deep) - 150.0) < 10.0
    assert np.isfinite(deep).all()


def test_pitch_shift_raises_frequency() -> None:
    tone = _tone(200.0)
    bright = _apply_pitch_shift(tone, _SR, 1.2)
    assert abs(_dominant_freq(bright) - 240.0) < 12.0


def test_pitch_shift_neutral_ratio_is_a_no_op() -> None:
    samples = np.linspace(-1.0, 1.0, 100, dtype=np.float32)
    assert _apply_pitch_shift(samples, _SR, 1.0) is samples


def test_short_buffer_still_returns_finite_audio() -> None:
    tiny = np.linspace(-1.0, 1.0, 64, dtype=np.float32)
    stretched = _time_stretch(tiny, _SR, 1.4)
    shifted = _apply_pitch_shift(tiny, _SR, 0.84)
    assert np.isfinite(stretched).all() and stretched.size > 0
    assert np.isfinite(shifted).all() and shifted.size > 0
