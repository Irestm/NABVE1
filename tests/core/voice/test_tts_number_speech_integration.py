from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import core.voice.tts as tts_module
from core.voice.tts import TextToSpeech


@dataclass(frozen=True)
class _NeutralStyle:
    prosody_rate: float = 1.0


def _make_tts(monkeypatch) -> TextToSpeech:
    monkeypatch.setattr(tts_module, "_breath_effect_enabled", lambda: False)
    monkeypatch.setattr(tts_module, "get_current_style", lambda: _NeutralStyle())
    monkeypatch.setattr(tts_module, "resolve_voice_prosody_rate", lambda speaker: 1.0)
    monkeypatch.setattr(tts_module, "resolve_voice_pitch_shift", lambda speaker: 1.0)
    return TextToSpeech(settings=object())  # unused once _synthesize_raw is replaced below


def test_synthesize_spells_out_numbers_before_calling_the_engine(monkeypatch) -> None:
    # Regression, found live: Silero's own text normalizer silently drops
    # (or, for a bare number, crashes on) plain digits - see
    # core/voice/number_speech.py's own docstring. synthesize() must never
    # hand raw digits to _synthesize_raw.
    tts = _make_tts(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        tts,
        "_synthesize_raw",
        lambda text, language, speaker: (seen.append(text), (np.ones(10, dtype=np.float32), 48000))[1],
    )

    tts.synthesize("температура 22 градуса", "ru")

    assert seen == ["температура двадцать два градуса"]


def test_synthesize_leaves_numberless_text_unaffected(monkeypatch) -> None:
    tts = _make_tts(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        tts,
        "_synthesize_raw",
        lambda text, language, speaker: (seen.append(text), (np.ones(10, dtype=np.float32), 48000))[1],
    )

    tts.synthesize("какая погода в киеве", "ru")

    assert seen == ["какая погода в киеве"]
