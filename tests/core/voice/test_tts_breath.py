from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import core.voice.tts as tts_module
from core.voice.sound_effects import BREATH_MARKER
from core.voice.tts import TextToSpeech


@dataclass(frozen=True)
class _NeutralStyle:
    prosody_rate: float = 1.0


def _make_tts(monkeypatch, *, breath_enabled: bool) -> TextToSpeech:
    # Isolate from whatever this machine's real profile database happens to
    # have persisted (communication style, selected voice variant) - these
    # tests care only about the marker-splicing logic, not the real prosody
    # values, which is a separate, already-covered concern
    # (test_tts_prosody.py).
    monkeypatch.setattr(tts_module, "_breath_effect_enabled", lambda: breath_enabled)
    monkeypatch.setattr(tts_module, "get_current_style", lambda: _NeutralStyle())
    monkeypatch.setattr(tts_module, "resolve_voice_prosody_rate", lambda speaker: 1.0)
    monkeypatch.setattr(tts_module, "resolve_voice_pitch_shift", lambda speaker: 1.0)
    return TextToSpeech(settings=object())  # unused once _synthesize_raw is replaced below


def test_no_marker_means_no_breath_sound_even_when_enabled(monkeypatch) -> None:
    tts = _make_tts(monkeypatch, breath_enabled=True)
    monkeypatch.setattr(
        tts, "_synthesize_raw", lambda text, language, speaker: (np.ones(100, dtype=np.float32), 48000)
    )

    samples, _ = tts.synthesize("Обычный ответ без паузы.", "ru")

    assert samples.size == 100  # unchanged - no breath spliced in anywhere


def test_marker_present_but_effect_disabled_is_left_as_plain_text(monkeypatch) -> None:
    tts = _make_tts(monkeypatch, breath_enabled=False)
    calls: list[str] = []
    monkeypatch.setattr(
        tts, "_synthesize_raw", lambda text, language, speaker: (calls.append(text), (np.ones(10, dtype=np.float32), 48000))[1]
    )

    tts.synthesize(f"Текст с маркером {BREATH_MARKER} внутри.", "ru")

    # Marker feature is off - the whole string (marker included) goes to
    # synthesis as ordinary text in one call, not stripped/split at all.
    assert calls == [f"Текст с маркером {BREATH_MARKER} внутри."]


def test_marker_present_and_enabled_splices_breath_between_segments(monkeypatch) -> None:
    tts = _make_tts(monkeypatch, breath_enabled=True)
    calls: list[str] = []
    monkeypatch.setattr(
        tts, "_synthesize_raw", lambda text, language, speaker: (calls.append(text), (np.ones(10, dtype=np.float32), 48000))[1]
    )

    samples, sample_rate = tts.synthesize(f"Первая часть. {BREATH_MARKER} Вторая часть.", "ru")

    # The marker itself is never sent to synthesis - only the two real segments.
    assert calls == ["Первая часть.", "Вторая часть."]
    # Output is much longer than the two 10-sample segments alone - the
    # breath sound (plus its gap) was actually spliced in between them.
    assert samples.size > 20
    assert sample_rate == 48000


def test_marker_at_the_very_start_has_no_leading_empty_synthesis_call(monkeypatch) -> None:
    tts = _make_tts(monkeypatch, breath_enabled=True)
    calls: list[str] = []
    monkeypatch.setattr(
        tts, "_synthesize_raw", lambda text, language, speaker: (calls.append(text), (np.ones(10, dtype=np.float32), 48000))[1]
    )

    tts.synthesize(f"{BREATH_MARKER} Только одна часть.", "ru")

    assert calls == ["Только одна часть."]
