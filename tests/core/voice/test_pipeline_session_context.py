from __future__ import annotations

import numpy as np
import pytest

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


class _FakeTTS:
    def synthesize(self, text: str, language: str):
        return np.ones(1, dtype=np.float32), 16000


def _make_dispatched_loop(monkeypatch, *, command: Command) -> VoiceAssistantLoop:
    async def handler(_params: dict) -> dict:
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register(command.name, handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: command)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    return loop


def test_handle_command_records_last_exchange_for_a_rule_based_command(monkeypatch) -> None:
    # Regression: an elliptical follow-up ("а сегодня какая была?") has to
    # resolve against whatever the PREVIOUS turn was about, no matter which
    # tier resolved that previous turn — interpret()'s pure regex match
    # here is the most common case (weather_get itself is rule-based).
    command = Command(name="weather_get", params={"city": "Киев", "when": "tomorrow"})
    loop = _make_dispatched_loop(monkeypatch, command=command)

    loop._handle_command(_FakeSTT(["какая погода завтра в киеве"]), _FakeTTS())

    assert loop._last_exchange is not None
    assert "какая погода завтра в киеве" in loop._last_exchange
    assert "weather_get" in loop._last_exchange
    assert "Киев" in loop._last_exchange


def test_classify_via_ai_bridge_passes_last_exchange_as_context_hint(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)
    loop._last_exchange = "Пользователь спросил про погоду в Киеве на завтра."

    seen_hints: list[str | None] = []

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None, on_progress=None, context_hint=None):
        seen_hints.append(context_hint)
        return None, "Сегодня ясно, 20 градусов."

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(loop, "_maybe_continue_free_text", lambda command_stt, tts, language: (None, False))

    loop._classify_via_ai_bridge("а сегодня какая была", _FakeSTT([]), _FakeTTS(), "ru")

    assert seen_hints == ["Пользователь спросил про погоду в Киеве на завтра."]


def test_classify_via_ai_bridge_records_last_exchange_for_a_direct_answer(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)
    loop._last_exchange = None

    async def fake_resolve_free_text(text, commands, *, on_stream_chunk=None, on_progress=None, context_hint=None):
        return None, "Столица Франции — Париж."

    monkeypatch.setattr(pipeline_module.ai_router, "resolve_free_text", fake_resolve_free_text)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(loop, "_maybe_continue_free_text", lambda command_stt, tts, language: (None, False))

    loop._classify_via_ai_bridge("столица франции", _FakeSTT([]), _FakeTTS(), "ru")

    assert loop._last_exchange == "Пользователь спросил: «столица франции». Ассистент ответил: «Столица Франции — Париж.»."


def test_run_resets_last_exchange_on_each_fresh_activation(monkeypatch) -> None:
    loop = VoiceAssistantLoop(CommandDispatcher())
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)
    loop._last_exchange = "Стейл контекст от прошлой, уже закончившейся сессии."

    seen_at_handle_command: list[str | None] = []
    wait_calls = {"n": 0}

    def fake_wait(tts):
        wait_calls["n"] += 1
        if wait_calls["n"] == 1:
            return True
        loop._stop_event.set()
        return False

    def fake_handle(command_stt, tts):
        seen_at_handle_command.append(loop._last_exchange)
        # End this one conversation cleanly after a single command, so the
        # inner continuous-conversation loop exits and _run() goes back to
        # _wait_for_wake_or_pause (the second, stopping call above) instead
        # of calling fake_handle forever.
        loop._paused_event.set()
        return False

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)
    monkeypatch.setattr(loop, "_handle_command", fake_handle)

    loop._run()

    assert seen_at_handle_command == [None]  # reset before the first _handle_command of this activation
