from __future__ import annotations

import numpy as np

# Clamped range for the "Затяжка в ответе" delay — see
# modules.user_profile.domain.DELAY_SECONDS_KEY and PersonalityPanel.tsx's
# number input (same bounds enforced there).
MIN_DELAY_SECONDS = 0.3
MAX_DELAY_SECONDS = 3.0

_ROBOTIC_CARRIER_HZ = 40.0
_ROBOTIC_QUANTIZE_LEVELS = 24

_TUNNEL_LOWPASS_HZ = 2200.0
_TUNNEL_HIGHPASS_HZ = 250.0
_TUNNEL_ECHO_TAPS = ((0.045, 0.35), (0.09, 0.18))


def apply_response_delay(samples: np.ndarray, sample_rate: int, seconds: float) -> np.ndarray:
    """Prepends silence before the reply starts playing — a "затяжка"
    (deliberate pause) rather than an audio transform. Applied once, at the
    very start of the final waveform, so it works identically whether the
    reply also has a breath sound spliced in or a voice-fx pass applied."""
    seconds = max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, seconds))
    if sample_rate <= 0:
        return samples
    silence = np.zeros(int(sample_rate * seconds), dtype=np.float32)
    return np.concatenate([silence, samples.astype(np.float32, copy=False)])


def _moving_average(samples: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    """Same cheap moving-average low-pass approach as
    core/voice/sound_effects.py's _shaped_noise — good enough for a stylized
    effect, no scipy dependency needed."""
    if samples.size == 0 or cutoff_hz <= 0:
        return samples
    window = max(1, int(sample_rate / cutoff_hz))
    if window <= 1:
        return samples
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(samples, kernel, mode="same")


def tunnel_voice_effect(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """"Голос как в тоннеле": a crude band-pass (high-pass via
    signal-minus-lowpass, then low-pass the result) to muffle both highs and
    lows, plus a couple of short decaying echo taps for a closed-space
    feel. Pure numpy, matching the rest of the TTS effects pipeline."""
    samples = samples.astype(np.float32, copy=False)
    if samples.size == 0 or sample_rate <= 0:
        return samples

    low = _moving_average(samples, sample_rate, _TUNNEL_HIGHPASS_HZ)
    high_passed = samples - low
    band_passed = _moving_average(high_passed, sample_rate, _TUNNEL_LOWPASS_HZ)

    out = band_passed.copy()
    for delay_seconds, decay in _TUNNEL_ECHO_TAPS:
        delay_n = int(sample_rate * delay_seconds)
        if delay_n <= 0 or delay_n >= out.size:
            continue
        echo = np.zeros_like(band_passed)
        echo[delay_n:] = band_passed[:-delay_n] * decay
        out = out + echo

    peak = float(np.abs(out).max())
    original_peak = float(np.abs(samples).max())
    if peak > 0 and original_peak > 0:
        out = out * (original_peak / peak)
    return out.astype(np.float32)


def robotic_voice_effect(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """"Роботизированный голос": classic ring modulation (multiply by a
    sine carrier) plus light amplitude quantization (bit-crush) for a
    mechanical, stepped texture."""
    samples = samples.astype(np.float32, copy=False)
    if samples.size == 0 or sample_rate <= 0:
        return samples

    t = np.arange(samples.size, dtype=np.float32) / sample_rate
    carrier = np.sin(2 * np.pi * _ROBOTIC_CARRIER_HZ * t).astype(np.float32)
    modulated = samples * carrier

    quantized = np.round(modulated * _ROBOTIC_QUANTIZE_LEVELS) / _ROBOTIC_QUANTIZE_LEVELS

    peak = float(np.abs(quantized).max())
    original_peak = float(np.abs(samples).max())
    if peak > 0 and original_peak > 0:
        quantized = quantized * (original_peak / peak)
    return quantized.astype(np.float32)
