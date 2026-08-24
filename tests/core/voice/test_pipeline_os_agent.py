from __future__ import annotations

import asyncio

import numpy as np
import pytest

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.os_agent import session as os_agent_session
from modules.os_agent.domain import AgentSession
from modules.ui_automation.domain import UIElement, UIStep


@pytest.fixture(autouse=True)
def _reset_os_agent_session() -> None:
    os_agent_session._active = False
    yield
    os_agent_session._active = False


def _make_loop(dispatcher: CommandDispatcher | None = None) -> VoiceAssistantLoop:
    return VoiceAssistantLoop(dispatcher or CommandDispatcher())


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


def _run_coro_directly(coro, barge_in, language):
    return asyncio.run(coro)


def _patch_no_barge_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cancellable", _run_coro_directly)


def _patch_no_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )


# --- _resolve_active_os_agent_utterance -----------------------------------


def test_active_utterance_returns_none_when_mode_is_off() -> None:
    loop = _make_loop()
    assert loop._resolve_active_os_agent_utterance("открой браузер", "ru") is None


def test_active_utterance_recognizes_stop_phrase() -> None:
    os_agent_session.start()
    loop = _make_loop()

    command = loop._resolve_active_os_agent_utterance("стоп", "ru")

    assert command == Command(name="stop_os_agent", params={})


def test_active_utterance_treats_other_text_as_the_task() -> None:
    os_agent_session.start()
    loop = _make_loop()

    command = loop._resolve_active_os_agent_utterance("открой настройки и включи тёмную тему", "ru")

    assert command == Command(
        name="os_agent_run_task", params={"raw_text": "открой настройки и включи тёмную тему"}
    )


# --- _resolve_os_agent_start ------------------------------------------------


def test_resolve_os_agent_start_refuses_without_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module.os_agent_planner, "has_configured_key", lambda: False)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    interrupted = loop._resolve_os_agent_start(tts=None, response_language="ru")

    assert interrupted is False
    assert os_agent_session.is_active() is False
    assert spoken == [pipeline_module.os_agent_announce.no_key_refusal_text("ru")]


def test_resolve_os_agent_start_activates_with_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module.os_agent_planner, "has_configured_key", lambda: True)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    interrupted = loop._resolve_os_agent_start(tts=None, response_language="ru")

    assert interrupted is False
    assert os_agent_session.is_active() is True
    assert spoken == [pipeline_module.os_agent_announce.mode_started_text("ru")]


# --- _resolve_os_agent_task --------------------------------------------------


def _done_session(task: str = "какая тема сейчас включена?") -> AgentSession:
    return AgentSession(task=task, outcome="done", summary="Сейчас включена тёмная тема.")


def _pending_session() -> AgentSession:
    element = UIElement(index=0, role="push button", name="Сохранить", bbox=(0, 0, 10, 10))
    step = UIStep(action="click", element=element)
    session = AgentSession(task="сохрани файл", outcome="limit")
    session.pending = [step]
    session.journal = ["Запланировано: Нажимаю кнопку «Сохранить»."]
    return session


def test_resolve_os_agent_task_speaks_summary_when_nothing_was_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    os_agent_session.start()

    async def fake_run_task(raw_text: str) -> AgentSession:
        assert raw_text == "какая тема сейчас включена?"
        return _done_session()

    monkeypatch.setattr(pipeline_module.os_agent_runner, "run_task", fake_run_task)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="os_agent_run_task", params={"raw_text": "какая тема сейчас включена?"})
    interrupted = loop._resolve_os_agent_task(command, tts=None, command_stt=None, response_language="ru")

    assert interrupted is False
    assert spoken == ["Сейчас включена тёмная тема."]
    assert os_agent_session.is_active() is False


def test_resolve_os_agent_task_applies_the_queue_on_a_confirmed_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    _patch_no_recording(monkeypatch)
    os_agent_session.start()

    async def fake_run_task(raw_text: str) -> AgentSession:
        return _pending_session()

    monkeypatch.setattr(pipeline_module.os_agent_runner, "run_task", fake_run_task)

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("ui_action", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    # First spoken turn is the confirm question -> "да"; second (the
    # optional explain offer, since the queue was non-empty) -> "нет".
    command_stt = _FakeSTT(["да", "нет"])

    command = Command(name="os_agent_run_task", params={"raw_text": "сохрани файл"})
    interrupted = loop._resolve_os_agent_task(command, tts=None, command_stt=command_stt, response_language="ru")

    assert interrupted is False
    assert len(executed) == 1
    assert executed[0]["steps"] == [{"action": "click", "x": 5, "y": 5, "button": "left"}]
    assert spoken[-2] == "Готово."  # dispatch result, spoken before the explain offer
    assert spoken[-1] == pipeline_module.os_agent_announce.explain_offer_text("ru")
    assert os_agent_session.is_active() is False


def test_resolve_os_agent_task_discards_the_queue_on_a_confirmed_no(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    _patch_no_recording(monkeypatch)
    os_agent_session.start()

    async def fake_run_task(raw_text: str) -> AgentSession:
        return _pending_session()

    monkeypatch.setattr(pipeline_module.os_agent_runner, "run_task", fake_run_task)

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("ui_action", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    command_stt = _FakeSTT(["нет", "нет"])

    command = Command(name="os_agent_run_task", params={"raw_text": "сохрани файл"})
    interrupted = loop._resolve_os_agent_task(command, tts=None, command_stt=command_stt, response_language="ru")

    assert interrupted is False
    assert executed == []
    assert spoken[-2] == pipeline_module.os_agent_announce.cancelled_text("ru")
    assert os_agent_session.is_active() is False
