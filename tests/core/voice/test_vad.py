from __future__ import annotations

import numpy as np

from core.voice.vad import SpeechActivityDetector


def test_silence_is_not_classified_as_speech() -> None:
    vad = SpeechActivityDetector(16000, aggressiveness=2)
    silence = np.zeros(vad.frame_samples, dtype=np.float32)
    assert vad.is_speech(silence) is False


def test_loud_noise_is_classified_as_speech() -> None:
    vad = SpeechActivityDetector(16000, aggressiveness=2)
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(vad.frame_samples) * 0.3).astype(np.float32)
    assert vad.is_speech(noise) is True


def test_wrong_length_frame_is_treated_as_silence_not_an_error() -> None:
    vad = SpeechActivityDetector(16000, aggressiveness=2)
    short_frame = np.zeros(10, dtype=np.float32)
    assert vad.is_speech(short_frame) is False
