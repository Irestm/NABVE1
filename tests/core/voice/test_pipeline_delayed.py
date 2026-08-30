from __future__ import annotations

import numpy as np

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


class _ScheduleSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def schedule(self, uow, command, run_at, original_text, pre_confirmed=False):
        self.calls.append((command.name, pre_confirmed))
        return 1


def _loop(monkeypatch, dispatcher, resolved: Command | None) -> tuple[VoiceAssistantLoop, _ScheduleSpy, list[str]]:
    loop = VoiceAssistantLoop(dispatcher)
    spy = _ScheduleSpy()
    spoken: list[str] = []
    monkeypatch.setattr(pipeline_module, "delayed_service_layer", spy)
    monkeypatch.setattr(
        pipeline_module.delayed_resolver, "resolve_command", lambda remainder, lang: resolved
    )
    monkeypatch.setattr(
        pipeline_module.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32),
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    return loop, spy, spoken


def test_delayed_command_schedules_without_dispatching(monkeypatch) -> None:
    ran: list[str] = []

    async def open_app(_params):
        ran.append("open_app")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("open_app", open_app, dangerous=False, description="")
    loop, spy, spoken = _loop(monkeypatch, dispatcher, Command(name="open_app", params={"target": "браузер"}))

    result = loop._handle_command(_FakeSTT(["открой браузер через 10 минут"]), _FakeTTS())

    assert ran == []
    assert [c[0] for c in spy.calls] == ["open_app"]
    assert spy.calls[0][1] is False  # not pre-confirmed
    assert any("через 10 мин" in text for text in spoken)
    assert result is False


def test_unresolved_delayed_command_is_spoken_back(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop, spy, spoken = _loop(monkeypatch, dispatcher, None)

    loop._handle_command(_FakeSTT(["поболтай через 10 минут"]), _FakeTTS())

    assert spy.calls == []
    assert any("не понял" in text.lower() for text in spoken)


def test_dangerous_delayed_command_is_confirmed_then_scheduled_preconfirmed(monkeypatch) -> None:
    dispatcher = CommandDispatcher()

    async def shutdown(_params):
        return {}

    dispatcher.register("shutdown", shutdown, dangerous=True, description="")
    loop, spy, spoken = _loop(monkeypatch, dispatcher, Command(name="shutdown", params={}))
    # STT: [the command utterance, then the spoken "да" confirmation]
    result = loop._handle_command(_FakeSTT(["выключи компьютер через час", "да"]), _FakeTTS())

    assert [c[0] for c in spy.calls] == ["shutdown"]
    assert spy.calls[0][1] is True  # pre-confirmed
    assert result is False


def test_dangerous_delayed_command_declined_is_not_scheduled(monkeypatch) -> None:
    dispatcher = CommandDispatcher()

    async def shutdown(_params):
        return {}

    dispatcher.register("shutdown", shutdown, dangerous=True, description="")
    loop, spy, spoken = _loop(monkeypatch, dispatcher, Command(name="shutdown", params={}))

    loop._handle_command(_FakeSTT(["выключи компьютер через час", "нет не надо"]), _FakeTTS())

    assert spy.calls == []
    assert any("не откладываю" in text.lower() for text in spoken)
