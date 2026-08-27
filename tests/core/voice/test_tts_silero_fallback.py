from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import core.voice.tts as tts_module
from core.voice.tts import TextToSpeech


@dataclass(frozen=True)
class _FakeChunk:
    audio_float_array: object
    sample_rate: int


class _FakeVoice:
    def __init__(self, chunk: _FakeChunk) -> None:
        self._chunk = chunk
        self.config = type("Config", (), {"sample_rate": self._chunk.sample_rate})()

    def synthesize(self, text: str):
        return [self._chunk]


class _CrashingSilero:
    def synthesize(self, text: str, speaker: str | None = None):
        raise RuntimeError("simulated Silero crash")


def test_synthesize_raw_falls_back_to_piper_and_latches_on_silero_crash(monkeypatch) -> None:
    # Regression coverage for the exact mechanism behind the live bug this
    # session fixed (number_speech.spell_out_numbers): a bare digit used to
    # crash Silero here, and this latch is what turned that one crash into
    # every subsequent reply for the rest of the process silently losing
    # voice selection (Piper has no multi-speaker catalog). The trigger is
    # now eliminated at the source, but this fallback/latch mechanism
    # itself had no test at all - a regression here would go unnoticed.
    tts = TextToSpeech(settings=object())
    monkeypatch.setattr(tts, "_get_silero", lambda: _CrashingSilero())
    fake_chunk = _FakeChunk(audio_float_array=np.ones(5, dtype=np.float32), sample_rate=22050)
    monkeypatch.setattr(tts, "_get_voice", lambda language: _FakeVoice(fake_chunk))

    assert tts._silero_failed is False

    samples, sample_rate = tts._synthesize_raw("22", "ru", None)

    assert tts._silero_failed is True  # latched
    assert sample_rate == 22050
    assert samples.size == 5  # came from the Piper fallback, not Silero


def test_get_silero_returns_none_without_reconstructing_once_failed(monkeypatch, tmp_path) -> None:
    # This is the actual latch _synthesize_raw relies on: once a crash sets
    # _silero_failed, _get_silero() must short-circuit to None on every
    # later call instead of trying to load/use the checkpoint again.
    fake_settings = type(
        "FakeSettings",
        (),
        {"silero_ru_model_path": tmp_path / "model.pt", "silero_ru_speaker": "eugene"},
    )()
    tts = TextToSpeech(settings=fake_settings)
    tts._silero_failed = True

    construct_calls: list[object] = []
    monkeypatch.setattr(
        tts_module, "SileroVoice", lambda *a, **k: construct_calls.append(1) or object()
    )

    assert tts._get_silero() is None
    assert construct_calls == []  # never even tried to construct one
