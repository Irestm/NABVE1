from __future__ import annotations

import numpy as np

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.interruption import TurnCancelled
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


def _fake_run_cancellable_always_cancels(coro, barge_in, language):
    # Simulate a stop phrase heard immediately: never actually run the
    # coroutine (closing it avoids an unawaited-coroutine warning), just
    # raise, exactly like the real run_cancellable does when interrupted.
    coro.close()
    raise TurnCancelled


def test_stop_phrase_during_dispatch_prevents_command_from_executing(monkeypatch) -> None:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: Command(name="noop", params={}))
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "run_cancellable", _fake_run_cancellable_always_cancels)

    result = loop._handle_command(_FakeSTT(["сделай что-нибудь"]), _FakeTTS())

    assert executed == []
    # Like an interruption during speech, the loop listens again immediately
    # instead of requiring the wake word.
    assert result is True


def test_stop_phrase_during_open_app_resolution_is_not_swallowed_as_a_resolution_failure(monkeypatch) -> None:
    # Regression guard: _resolve_open_app_target (and the other _resolve_*
    # methods) wrap their run_cancellable call in `except Exception` for the
    # "resolution failed, fall back to raw text" case — TurnCancelled must
    # NOT be caught there, or a stop phrase heard during app-name resolution
    # would silently continue on to dispatch the raw/unresolved command
    # instead of actually stopping.
    executed: list[str] = []

    async def handler(params: dict) -> dict:
        executed.append(params.get("target"))
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("open_app", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(
        pipeline_module, "interpret", lambda text, language: Command(name="open_app", params={"target": "стим"})
    )
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "run_cancellable", _fake_run_cancellable_always_cancels)

    result = loop._handle_command(_FakeSTT(["открой стим"]), _FakeTTS())

    assert executed == []
    assert result is True
