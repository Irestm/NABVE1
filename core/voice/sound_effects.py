from __future__ import annotations

import numpy as np

# Quiet relative to speech (which sits close to full scale) — this is meant
# to read as a subtle atmospheric touch before the reply, not a sound effect
# competing with it.
_PEAK_AMPLITUDE = 0.14

_DRAG_DURATION_SECONDS = 0.6
_HOLD_DURATION_SECONDS = 0.15
_EXHALE_DURATION_SECONDS = 1.2

# Inserted into an AI-generated reply's text — see
# modules.ai_bridge.system_prompt's breath-marker instruction and
# core/voice/tts.py, which splits on this marker and stitches the actual
# generated sound in at that exact position instead of always prepending it
# before the whole reply. The model decides per-reply whether a marker
# belongs at all (and where) — see the instruction text for when it's told
# that's appropriate.
BREATH_MARKER = "[ЗАТЯЖКА]"


def _shaped_noise(rng: np.random.Generator, n_samples: int, sample_rate: int, smoothing_hz: float) -> np.ndarray:
    """Band-limits white noise via a moving-average low-pass — cheap, and a
    one-off sub-second effect doesn't justify a scipy dependency for a
    proper filter design. A higher `smoothing_hz` (narrower averaging
    window) keeps more high-frequency content (brighter, tighter — a
    "drag"); a lower one (wider window) sounds duller and airier (a
    breathy "exhale")."""
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    noise = rng.standard_normal(n_samples).astype(np.float32)
    window = max(1, int(sample_rate / smoothing_hz))
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(noise, kernel, mode="same")


def generate_breath_sound(sample_rate: int) -> np.ndarray:
    """A short, quiet synthesized "drag on a cigarette, then exhale" —
    spliced into a reply at the AI's own chosen BREATH_MARKER position when
    the effect is enabled (see modules.user_profile.domain.BREATH_EFFECT_KEY
    and core/voice/tts.py). Two shaped-noise phases with a brief silent
    hold in between: a tighter, brighter "drag" (quick attack, sharpish
    release), a beat of held silence, then a longer, breathier "exhale"
    (slow swell, long fade — a sigh, not a burst). Both phases are
    deliberately unhurried — this is meant to read as a deliberate,
    weighted pause, not a quick sound effect. Procedurally generated rather
    than a shipped audio asset — nothing to package or ship, and the
    character can be retuned here without touching a binary file."""
    if sample_rate <= 0:
        return np.zeros(0, dtype=np.float32)

    rng = np.random.default_rng()

    drag_n = int(sample_rate * _DRAG_DURATION_SECONDS)
    drag = _shaped_noise(rng, drag_n, sample_rate, smoothing_hz=3500)
    if drag_n > 0:
        drag_envelope = np.ones(drag_n, dtype=np.float32)
        attack = max(1, drag_n // 6)
        drag_envelope[:attack] = np.linspace(0.0, 1.0, attack, dtype=np.float32)
        release = max(1, drag_n // 4)
        drag_envelope[-release:] *= np.linspace(1.0, 0.3, release, dtype=np.float32)
        drag = drag * drag_envelope

    hold = np.zeros(int(sample_rate * _HOLD_DURATION_SECONDS), dtype=np.float32)

    exhale_n = int(sample_rate * _EXHALE_DURATION_SECONDS)
    exhale = _shaped_noise(rng, exhale_n, sample_rate, smoothing_hz=900)
    if exhale_n > 0:
        exhale_envelope = np.ones(exhale_n, dtype=np.float32)
        attack = max(1, exhale_n // 4)
        exhale_envelope[:attack] = np.linspace(0.0, 1.0, attack, dtype=np.float32)
        decay = exhale_n - attack
        if decay > 0:
            exhale_envelope[attack:] = np.linspace(1.0, 0.0, decay, dtype=np.float32) ** 1.3
        exhale = exhale * exhale_envelope * 0.8

    combined = np.concatenate([drag, hold, exhale])
    peak = float(np.abs(combined).max())
    if peak > 0:
        combined = combined / peak * _PEAK_AMPLITUDE
    return combined.astype(np.float32)
