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
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "run_cancellable", _fake_run_cancellable_always_cancels)

    result = loop._handle_command(_FakeSTT(["сделай что-нибудь"]), _FakeTTS())

    assert executed == []
    # True here means "the user's stop word interrupted a spoken reply" -
    # _run() reacts to that by pausing (see core/voice/pipeline.py's _run),
    # not by dispatching anything.
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
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "run_cancellable", _fake_run_cancellable_always_cancels)

    result = loop._handle_command(_FakeSTT(["открой стим"]), _FakeTTS())

    assert executed == []
    assert result is True


def test_stop_word_spoken_as_the_command_itself_pauses_instead_of_running_anything(monkeypatch) -> None:
    # Regression: the stop word used to only be checked in
    # _wait_for_wake_or_pause's own listening pass (before the wake word) or
    # via BargeInMonitor while a reply is being spoken. Saying it right
    # after waking - so it becomes the transcribed command text itself - was
    # never checked against anything: it fell through interpret() as
    # ordinary unmatched text into _classify_via_ai_bridge, the "stuck on
    # Уточняю у ИИ" symptom this closes.
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(
        pipeline_module.profile_service_layer,
        "get_fact",
        lambda uow, key: "стоп" if key is pipeline_module.STOP_WORD_KEY else None,
    )
    # interpret() would happily match "noop" here if the stop-word check
    # didn't short-circuit first - proves the check runs before interpret(),
    # not just before dispatch.
    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: Command(name="noop", params={}))
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )

    result = loop._handle_command(_FakeSTT(["стоп"]), _FakeTTS())

    assert executed == []
    assert result is False
    assert loop._paused_event.is_set()


def test_record_command_audio_brackets_recording_with_a_recording_context_barge_in_monitor(monkeypatch) -> None:
    loop = VoiceAssistantLoop(CommandDispatcher())
    monitor_calls: list[tuple[str, str]] = []

    def fake_run(language, stop_event, interrupted, *, context="speaking"):
        monitor_calls.append((language, context))

    monkeypatch.setattr(loop._barge_in, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.ones(3, dtype=np.float32),
    )

    audio, interrupted = loop._record_command_audio()

    assert audio.size == 3
    assert interrupted is False
    assert monitor_calls == [(loop._settings.fallback_language, "recording")]


def test_record_command_audio_reports_interrupted_when_monitor_hears_the_stop_word(monkeypatch) -> None:
    loop = VoiceAssistantLoop(CommandDispatcher())

    def fake_run(language, stop_event, interrupted, *, context="speaking"):
        interrupted.set()
        stop_event.set()

    monkeypatch.setattr(loop._barge_in, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.zeros(0, dtype=np.float32),
    )

    audio, interrupted = loop._record_command_audio()

    assert interrupted is True


def test_handle_command_returns_true_immediately_when_recording_itself_is_interrupted(monkeypatch) -> None:
    # The initial command recording, not just AI classification/dispatch,
    # must now also be barge-in-interruptible - saying the stop word while
    # still mid-utterance should never reach interpret()/dispatch at all.
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: Command(name="noop", params={}))
    monkeypatch.setattr(loop, "_record_command_audio", lambda: (np.ones(1, dtype=np.float32), True))

    result = loop._handle_command(_FakeSTT(["стоп"]), _FakeTTS())

    assert executed == []
    assert result is True


def test_stop_phrase_during_ai_bridge_classification_is_not_swallowed_as_a_classification_failure(monkeypatch) -> None:
    # Regression: _classify_via_ai_bridge used to call asyncio.run(run())
    # directly instead of run_cancellable, so a stop phrase said while
    # stuck on "Уточняю у ИИ" was never heard at all — no BargeInMonitor
    # ran for the classify()/provider-chain round-trip, only later, once a
    # streamed local-model answer actually started speaking. Also guards
    # that TurnCancelled isn't swallowed by the surrounding
    # `except Exception` ("AI intent classification failed, apologize").
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(pipeline_module.command_classifier, "match_system_command", lambda text: None)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(pipeline_module, "run_cancellable", _fake_run_cancellable_always_cancels)

    result = loop._handle_command(_FakeSTT(["какая-то непонятная фраза"]), _FakeTTS())

    assert executed == []
    assert result is True
