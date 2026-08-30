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


def _loop(monkeypatch, dispatcher: CommandDispatcher, mapping: dict[str, Command | None]) -> VoiceAssistantLoop:
    loop = VoiceAssistantLoop(dispatcher)
    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: mapping.get(text.strip()))
    monkeypatch.setattr(
        pipeline_module.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32),
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module.command_classifier, "match_system_command", lambda text: None)
    return loop


def test_each_part_runs_in_spoken_order(monkeypatch) -> None:
    order: list[str] = []

    async def mute(_params):
        order.append("mute")
        return {}

    async def minimize(_params):
        order.append("minimize")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    dispatcher.register("minimize_window", minimize, dangerous=False, description="")
    loop = _loop(
        monkeypatch,
        dispatcher,
        {
            "выключи звук": Command(name="mute", params={}),
            "сверни окно": Command(name="minimize_window", params={}),
        },
    )
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    result = loop._handle_command(_FakeSTT(["выключи звук и сверни окно"]), _FakeTTS())

    assert order == ["mute", "minimize"]
    assert result is False


def test_unrecognized_part_is_spoken_back(monkeypatch) -> None:
    executed: list[str] = []

    async def mute(_params):
        executed.append("mute")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    loop = _loop(monkeypatch, dispatcher, {"выключи звук": Command(name="mute", params={})})
    monkeypatch.setattr(loop, "_classify_via_ai_bridge", lambda *a, **k: (None, False))
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    result = loop._handle_command(_FakeSTT(["выключи звук и станцуй лезгинку"]), _FakeTTS())

    assert executed == ["mute"]
    assert any("станцуй лезгинку" in text for text in spoken)
    assert result is False


def test_barge_in_on_the_first_part_stops_the_rest(monkeypatch) -> None:
    order: list[str] = []

    async def mute(_params):
        order.append("mute")
        return {}

    async def minimize(_params):
        order.append("minimize")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    dispatcher.register("minimize_window", minimize, dangerous=False, description="")
    loop = _loop(
        monkeypatch,
        dispatcher,
        {
            "выключи звук": Command(name="mute", params={}),
            "сверни окно": Command(name="minimize_window", params={}),
        },
    )
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: True)

    result = loop._handle_command(_FakeSTT(["выключи звук и сверни окно"]), _FakeTTS())

    assert order == ["mute"]
    assert result is True


def test_a_plain_single_command_is_unchanged(monkeypatch) -> None:
    executed: list[str] = []

    async def mute(_params):
        executed.append("mute")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    loop = _loop(monkeypatch, dispatcher, {"выключи звук": Command(name="mute", params={})})
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    result = loop._handle_command(_FakeSTT(["выключи звук"]), _FakeTTS())

    assert executed == ["mute"]
    assert result is False
