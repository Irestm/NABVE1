from __future__ import annotations

import numpy as np

from modules.discussion_mode import speaker_diarization as sd


def _tone(freq: float, sr: int = 16000, seconds: float = 0.4) -> np.ndarray:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_estimate_f0_recovers_a_pure_tone() -> None:
    estimate = sd.estimate_f0(_tone(150.0), 16000)
    assert estimate is not None
    assert abs(estimate - 150.0) < 8.0


def test_estimate_f0_returns_none_for_silence() -> None:
    assert sd.estimate_f0(np.zeros(8000, dtype=np.float32), 16000) is None


def test_two_distinct_pitches_are_two_speakers() -> None:
    centroids: list[float] = []
    assert sd.estimate_speaker(_tone(120.0), 16000, centroids) == "спикер 1"
    assert sd.estimate_speaker(_tone(122.0), 16000, centroids) == "спикер 1"  # same voice
    assert sd.estimate_speaker(_tone(240.0), 16000, centroids) == "спикер 2"  # clearly higher
    assert len(centroids) == 2


def test_third_voice_maps_to_nearest_existing_speaker() -> None:
    centroids = [120.0, 240.0]
    assert sd.estimate_speaker(_tone(235.0), 16000, centroids) == "спикер 2"
    assert len(centroids) == 2


def test_unvoiced_window_falls_back_without_crashing() -> None:
    noise = (np.random.default_rng(1).normal(0, 0.001, 8000)).astype(np.float32)
    result = sd.estimate_speaker(noise, 16000, [])
    assert result.startswith("спикер ")
