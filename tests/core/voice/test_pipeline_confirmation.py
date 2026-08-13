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


def _make_dangerous_dispatcher() -> tuple[CommandDispatcher, list[str]]:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("shutdown")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("shutdown", handler, dangerous=True, description="")
    return dispatcher, executed


def test_confirmation_prompt_barge_in_still_reaches_the_confirm_step(monkeypatch) -> None:
    """Regression: if _speak_safely returned True (interrupted) while
    speaking the CONFIRMATION_REQUIRED question itself, _handle_command used
    to bail out immediately and never record/check the user's actual answer
    - the pending token was silently abandoned, and the next thing the user
    said (e.g. "да") was processed as a brand new top-level command instead
    of a confirmation. This reproduces that exact interruption and asserts
    the dangerous command still gets confirmed and executed."""
    dispatcher, executed = _make_dangerous_dispatcher()
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: Command(name="shutdown", params={}))
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)

    # First _speak_safely call (the confirmation question) is interrupted;
    # every subsequent call (the final "Command executed" reply) is not.
    speak_calls: list[str] = []

    def fake_speak_safely(tts, text, language) -> bool:
        speak_calls.append(text)
        return len(speak_calls) == 1

    monkeypatch.setattr(loop, "_speak_safely", fake_speak_safely)

    command_stt = _FakeSTT(["выключи компьютер", "да"])
    tts = _FakeTTS()

    loop._handle_command(command_stt, tts)

    assert executed == ["shutdown"]
    assert len(speak_calls) == 2  # the question, then the final result


def test_confirmation_declined_still_resolves_the_token_instead_of_leaking_it(monkeypatch) -> None:
    dispatcher, executed = _make_dangerous_dispatcher()
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: Command(name="shutdown", params={}))
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command_stt = _FakeSTT(["выключи компьютер", "нет отмена"])
    tts = _FakeTTS()

    loop._handle_command(command_stt, tts)

    assert executed == []
    assert dispatcher._pending == {}
