from __future__ import annotations

from core.models import AssistantState
from core.state import state_manager
from core.voice.proactive_announcer import ProactiveAnnouncer
from modules.hardware_adaptive.events import HardwareAlertRaised


class _FakeVoiceLoop:
    def __init__(self, running: bool) -> None:
        self.is_running = running


class _FakeTts:
    def __init__(self) -> None:
        self.spoken: list[tuple[str, str]] = []

    def speak(self, text: str, language: str, speaker: str | None = None) -> None:
        self.spoken.append((text, language))


def _event() -> HardwareAlertRaised:
    return HardwareAlertRaised(metric="battery", severity="warning", message="Батарея разряжена", value=10.0)


async def test_does_not_speak_when_voice_loop_not_running(monkeypatch) -> None:
    announcer = ProactiveAnnouncer(_FakeVoiceLoop(running=False))
    fake_tts = _FakeTts()
    monkeypatch.setattr(announcer, "_tts", fake_tts)

    await announcer.handle(_event())

    assert fake_tts.spoken == []


async def test_speaks_when_idle_and_voice_loop_running(monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "_state", AssistantState.IDLE)
    announcer = ProactiveAnnouncer(_FakeVoiceLoop(running=True))
    fake_tts = _FakeTts()
    monkeypatch.setattr(announcer, "_tts", fake_tts)

    await announcer.handle(_event())

    assert fake_tts.spoken == [("Батарея разряжена", "ru")]


async def test_does_not_speak_while_assistant_is_speaking(monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "_state", AssistantState.SPEAKING)
    announcer = ProactiveAnnouncer(_FakeVoiceLoop(running=True))
    fake_tts = _FakeTts()
    monkeypatch.setattr(announcer, "_tts", fake_tts)

    await announcer.handle(_event())

    assert fake_tts.spoken == []
