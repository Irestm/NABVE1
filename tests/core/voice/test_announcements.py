from __future__ import annotations

from datetime import datetime

import pytest

from core.voice import announcements
from core.voice.announcements import ReminderAnnouncer
from core.voice.config import VoiceSettings
from modules.calendar.events import ReminderDue


class _FakeVoiceLoop:
    def __init__(self, running: bool) -> None:
        self.is_running = running


class _FakeTTS:
    def __init__(self, _settings: VoiceSettings) -> None:
        self.calls: list[tuple[str, str]] = []

    def speak(self, text: str, language: str) -> None:
        self.calls.append((text, language))


class _RaisingTTS:
    def __init__(self, _settings: VoiceSettings) -> None:
        pass

    def speak(self, text: str, language: str) -> None:
        raise RuntimeError("synthesis blew up")


def _event() -> ReminderDue:
    return ReminderDue(event_id=42, title="Позвонить маме", event_time=datetime(2026, 1, 1, 9, 0))


async def test_handle_does_nothing_when_voice_loop_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(announcements, "TextToSpeech", _FakeTTS)
    announcer = ReminderAnnouncer(_FakeVoiceLoop(running=False))

    await announcer.handle(_event())

    assert announcer._tts is None


async def test_handle_speaks_the_reminder_when_voice_loop_is_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(announcements, "TextToSpeech", _FakeTTS)
    settings = VoiceSettings(response_language_override=None)
    announcer = ReminderAnnouncer(_FakeVoiceLoop(running=True), settings=settings)

    await announcer.handle(_event())

    assert announcer._tts is not None
    assert announcer._tts.calls == [("Напоминание: Позвонить маме", "ru")]


async def test_handle_uses_response_language_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(announcements, "TextToSpeech", _FakeTTS)
    settings = VoiceSettings(response_language_override="en")
    announcer = ReminderAnnouncer(_FakeVoiceLoop(running=True), settings=settings)

    await announcer.handle(_event())

    assert announcer._tts.calls[0][1] == "en"


async def test_handle_swallows_tts_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(announcements, "TextToSpeech", _RaisingTTS)
    announcer = ReminderAnnouncer(_FakeVoiceLoop(running=True))

    await announcer.handle(_event())  # must not raise
