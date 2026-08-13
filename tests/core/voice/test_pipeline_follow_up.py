from __future__ import annotations

import dataclasses

import numpy as np

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.config import voice_settings
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult


def _make_loop(**settings_overrides: object) -> VoiceAssistantLoop:
    settings = dataclasses.replace(voice_settings, **settings_overrides) if settings_overrides else voice_settings
    return VoiceAssistantLoop(CommandDispatcher(), settings)


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


# --- _maybe_continue_free_text ---------------------------------------------


def test_disabled_when_follow_up_window_is_zero(monkeypatch) -> None:
    loop = _make_loop(follow_up_window_seconds=0.0)
    called = []
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda *a, **k: called.append(1)
    )

    result = loop._maybe_continue_free_text(_FakeSTT([]), tts=None, response_language="ru")

    assert result == (None, False)
    assert called == []  # never even tries to listen


def test_returns_none_false_on_silence(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda *a, **k: np.zeros(0, dtype=np.float32)
    )

    result = loop._maybe_continue_free_text(_FakeSTT([]), tts=None, response_language="ru")

    assert result == (None, False)


def test_listens_with_onset_timeout_from_settings(monkeypatch) -> None:
    loop = _make_loop(follow_up_window_seconds=7.0)
    captured: dict = {}

    def fake_record(settings, stop_event, *, onset_timeout_seconds=None):
        captured["onset_timeout_seconds"] = onset_timeout_seconds
        return np.zeros(0, dtype=np.float32)

    monkeypatch.setattr(pipeline_module.audio_io, "record_until_silence", fake_record)

    loop._maybe_continue_free_text(_FakeSTT([]), tts=None, response_language="ru")

    assert captured["onset_timeout_seconds"] == 7.0


def test_recurses_into_classify_via_ai_bridge_on_captured_follow_up(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda *a, **k: np.ones(10, dtype=np.float32)
    )

    recorded: dict = {}

    def fake_classify(text, command_stt, tts, response_language):
        recorded["text"] = text
        return None, False

    monkeypatch.setattr(loop, "_classify_via_ai_bridge", fake_classify)

    stt = _FakeSTT(["а что насчёт завтра"])
    result = loop._maybe_continue_free_text(stt, tts=None, response_language="ru")

    assert recorded["text"] == "а что насчёт завтра"
    assert result == (None, False)


def test_empty_transcription_does_not_recurse(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda *a, **k: np.ones(10, dtype=np.float32)
    )
    called = []
    monkeypatch.setattr(loop, "_classify_via_ai_bridge", lambda *a, **k: called.append(1))

    stt = _FakeSTT(["   "])
    result = loop._maybe_continue_free_text(stt, tts=None, response_language="ru")

    assert result == (None, False)
    assert called == []


# --- _classify_via_ai_bridge opening the follow-up window -----------------


def test_opens_follow_up_after_uninterrupted_direct_answer(monkeypatch) -> None:
    loop = _make_loop()

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None):
        return None, "Ответ от облака."

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)  # not interrupted

    follow_up_calls: list[int] = []
    monkeypatch.setattr(
        loop,
        "_maybe_continue_free_text",
        lambda command_stt, tts, language: (follow_up_calls.append(1), (None, False))[1],
    )

    result = loop._classify_via_ai_bridge("вопрос", _FakeSTT([]), tts=None, response_language="ru")

    assert result == (None, False)
    assert follow_up_calls == [1]


def test_skips_follow_up_when_answer_was_interrupted(monkeypatch) -> None:
    loop = _make_loop()

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None):
        return None, "Ответ от облака."

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: True)  # interrupted

    follow_up_calls: list[int] = []
    monkeypatch.setattr(
        loop,
        "_maybe_continue_free_text",
        lambda command_stt, tts, language: (follow_up_calls.append(1), (None, False))[1],
    )

    result = loop._classify_via_ai_bridge("вопрос", _FakeSTT([]), tts=None, response_language="ru")

    assert result == (None, True)
    assert follow_up_calls == []


def test_skips_follow_up_when_resolved_to_a_dispatchable_command(monkeypatch) -> None:
    loop = _make_loop()

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None):
        return Command(name="open_app", params={"target": "steam"}), None

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)

    follow_up_calls: list[int] = []
    monkeypatch.setattr(
        loop,
        "_maybe_continue_free_text",
        lambda command_stt, tts, language: (follow_up_calls.append(1), (None, False))[1],
    )

    result = loop._classify_via_ai_bridge("открой стим", _FakeSTT([]), tts=None, response_language="ru")

    assert result == (Command(name="open_app", params={"target": "steam"}), False)
    assert follow_up_calls == []


def test_skips_follow_up_when_nothing_usable_came_back(monkeypatch) -> None:
    loop = _make_loop()

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None):
        return None, None

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    follow_up_calls: list[int] = []
    monkeypatch.setattr(
        loop,
        "_maybe_continue_free_text",
        lambda command_stt, tts, language: (follow_up_calls.append(1), (None, False))[1],
    )

    result = loop._classify_via_ai_bridge("бессвязица", _FakeSTT([]), tts=None, response_language="ru")

    assert result == (None, False)
    assert follow_up_calls == []
