from __future__ import annotations

from pathlib import Path

import numpy as np

from core.voice.stt import TranscriptionResult
from modules.meeting_recorder import adapters as adapters_module
from modules.meeting_recorder.adapters import LocalWhisperMeetingTranscriber


def _result(text: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, detected_language="ru", language_probability=0.99)


def test_transcribe_skips_a_failing_chunk_instead_of_losing_the_whole_transcript(monkeypatch) -> None:
    """Regression: a single chunk raising used to propagate straight out of
    transcribe(), which modules.meeting_recorder.service_layer.
    transcribe_next then turned into transcript_status=ERROR for the WHOLE
    recording — discarding every chunk successfully transcribed before the
    failure. One bad window should degrade to "missing that bit of text",
    not "no transcript at all"."""
    transcriber = LocalWhisperMeetingTranscriber(chunk_seconds=1)
    chunk_samples = adapters_module.voice_settings.sample_rate  # 1s of audio per chunk
    monkeypatch.setattr(
        adapters_module.crm_transcriber,
        "decode_audio_file",
        lambda path: np.zeros(chunk_samples * 3, dtype=np.float32),
    )

    calls: list[int] = []

    def fake_transcribe(chunk_audio):
        calls.append(len(calls))
        if len(calls) == 2:
            raise RuntimeError("simulated STT failure on the middle chunk")
        return _result(f"piece-{len(calls)}")

    monkeypatch.setattr(transcriber._stt, "transcribe", fake_transcribe)

    progress: list[float] = []
    text = transcriber.transcribe(Path("/tmp/does-not-matter.ogg"), on_progress=progress.append)

    # Chunk 2's failure is skipped, not fatal — chunks 1 and 3 still land.
    assert text == "piece-1 piece-3"
    assert len(calls) == 3
    assert progress == [1 / 3, 2 / 3, 1.0]


def test_transcribe_returns_empty_string_for_empty_audio(monkeypatch) -> None:
    transcriber = LocalWhisperMeetingTranscriber(chunk_seconds=1)
    monkeypatch.setattr(
        adapters_module.crm_transcriber, "decode_audio_file", lambda path: np.zeros(0, dtype=np.float32)
    )

    progress: list[float] = []
    text = transcriber.transcribe(Path("/tmp/empty.ogg"), on_progress=progress.append)

    assert text == ""
    assert progress == [1.0]
