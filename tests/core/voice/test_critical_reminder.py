from __future__ import annotations

import asyncio

import numpy as np
import pytest

import core.os_adapter as os_adapter_pkg
import core.voice.critical_reminder as critical_reminder
from core.models import AssistantState
from core.state import state_manager
from core.voice import web_pipeline
from core.voice.critical_reminder import CriticalReminderHandler
from modules.calendar.events import ReminderDue


class _FakeAdapter:
    def __init__(self) -> None:
        self.paused_calls = 0
        self.resumed_with: list[list[str]] = []

    def pause_media(self) -> list[str]:
        self.paused_calls += 1
        return ["firefox"]

    def resume_media(self, tokens):
        self.resumed_with.append(list(tokens))


class _FakeTTS:
    def __init__(self, *_a, **_k) -> None:
        self.said: list[str] = []

    def speak(self, text: str, language: str) -> None:
        self.said.append(text)


class _FakeSTT:
    def __init__(self, replies: list[str]) -> None:
        self._replies = iter(replies)

    def transcribe(self, _audio):
        class _R:
            text = next(self._replies)

        return _R()


class _FakeLoop:
    is_running = True


def _wire(monkeypatch, adapter: _FakeAdapter, stt_replies: list[str]) -> _FakeTTS:
    tts = _FakeTTS()
    monkeypatch.setattr(os_adapter_pkg, "get_os_adapter", lambda: adapter)
    monkeypatch.setattr(critical_reminder, "TextToSpeech", lambda *_a, **_k: tts)
    monkeypatch.setattr(
        critical_reminder.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.ones(4, dtype=np.float32),
    )
    monkeypatch.setattr(web_pipeline, "_stt", _FakeSTT(stt_replies))
    return tts


@pytest.fixture(autouse=True)
def _reset_state():
    state_manager.set_state(AssistantState.IDLE)
    yield
    state_manager.set_state(AssistantState.IDLE)


def test_non_critical_event_is_ignored(monkeypatch) -> None:
    adapter = _FakeAdapter()
    _wire(monkeypatch, adapter, [])
    handler = CriticalReminderHandler(_FakeLoop())

    asyncio.run(handler.handle(ReminderDue(event_id=1, title="X", event_time=None, critical=False)))

    assert adapter.paused_calls == 0


def test_critical_event_pauses_speaks_waits_ack_and_resumes(monkeypatch) -> None:
    adapter = _FakeAdapter()
    tts = _wire(monkeypatch, adapter, ["понял"])
    handler = CriticalReminderHandler(_FakeLoop())

    asyncio.run(
        handler.handle(ReminderDue(event_id=1, title="Позвонить врачу", event_time=None, critical=True))
    )

    assert adapter.paused_calls == 1
    assert adapter.resumed_with == [["firefox"]]
    assert any("Позвонить врачу" in line for line in tts.said)
    assert state_manager.state is AssistantState.IDLE


def test_non_acknowledgement_retries_then_gives_up(monkeypatch) -> None:
    adapter = _FakeAdapter()
    tts = _wire(monkeypatch, adapter, ["что", "не сейчас", "перезвоню", "потом", "ммм"])
    handler = CriticalReminderHandler(_FakeLoop())

    asyncio.run(handler.handle(ReminderDue(event_id=1, title="X", event_time=None, critical=True)))

    # media still restored even though the user never acknowledged
    assert adapter.resumed_with == [["firefox"]]
    # prompted to acknowledge on each of the first attempts
    assert tts.said.count("Скажите «понял», чтобы продолжить.") >= 3


def test_takeover_skipped_when_voice_loop_not_running(monkeypatch) -> None:
    adapter = _FakeAdapter()
    _wire(monkeypatch, adapter, [])

    class _StoppedLoop:
        is_running = False

    handler = CriticalReminderHandler(_StoppedLoop())
    asyncio.run(handler.handle(ReminderDue(event_id=1, title="X", event_time=None, critical=True)))

    assert adapter.paused_calls == 0
