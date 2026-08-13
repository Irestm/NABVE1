from __future__ import annotations

import numpy as np

from core.voice.sound_effects import generate_breath_sound

# 0.6s drag + 0.15s hold + 1.2s exhale.
_DRAG_SECONDS = 0.6
_HOLD_SECONDS = 0.15
_EXHALE_SECONDS = 1.2


def test_generates_expected_total_duration_at_given_sample_rate() -> None:
    sample_rate = 48000
    breath = generate_breath_sound(sample_rate)
    expected = (
        int(sample_rate * _DRAG_SECONDS) + int(sample_rate * _HOLD_SECONDS) + int(sample_rate * _EXHALE_SECONDS)
    )
    assert breath.size == expected


def test_output_is_float32() -> None:
    assert generate_breath_sound(16000).dtype == np.float32


def test_is_quiet_relative_to_full_scale_speech() -> None:
    breath = generate_breath_sound(48000)
    assert 0 < float(np.abs(breath).max()) <= 0.15


def test_starts_near_silence() -> None:
    # The drag phase has a quick attack from zero, so the very first
    # samples shouldn't be an abrupt on/off click.
    breath = generate_breath_sound(48000)
    assert abs(breath[0]) < 0.01


def test_has_a_silent_hold_between_drag_and_exhale() -> None:
    sample_rate = 48000
    breath = generate_breath_sound(sample_rate)
    drag_samples = int(sample_rate * _DRAG_SECONDS)
    hold_samples = int(sample_rate * _HOLD_SECONDS)
    hold_region = breath[drag_samples : drag_samples + hold_samples]
    assert hold_region.size > 0
    assert np.abs(hold_region).max() == 0.0


def test_zero_or_negative_sample_rate_returns_empty() -> None:
    assert generate_breath_sound(0).size == 0
