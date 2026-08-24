from __future__ import annotations

import numpy as np

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


def test_resolve_analyze_active_editor_asks_for_the_task(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="analyze_active_editor", params={})
    command_stt = _FakeSTT(["найди баг"])

    result, interrupted = loop._resolve_analyze_active_editor(
        command, command_stt, tts=None, response_language="ru"
    )

    assert interrupted is False
    assert result == Command(name="analyze_active_editor", params={"instruction": "найди баг"})


def test_resolve_analyze_active_editor_gives_up_on_empty_answer(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="analyze_active_editor", params={})
    command_stt = _FakeSTT([""])

    result, interrupted = loop._resolve_analyze_active_editor(
        command, command_stt, tts=None, response_language="ru"
    )

    assert result is None


def test_resolve_analyze_active_editor_stops_when_the_question_is_interrupted(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: True)

    command = Command(name="analyze_active_editor", params={})

    result, interrupted = loop._resolve_analyze_active_editor(
        command, command_stt=None, tts=None, response_language="ru"
    )

    assert result is None
    assert interrupted is True
