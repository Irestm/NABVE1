from __future__ import annotations

import numpy as np
import pytest

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.discussion_mode.state import session as discussion_session
from modules.user_profile.domain import ASSISTANT_NAME_KEY


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        try:
            text = next(self._texts)
        except StopIteration:
            text = "выйди из режима дискуссии"  # safety net so a loop can't spin
        return TranscriptionResult(text=text, detected_language="ru", language_probability=0.99)


class _FakeTTS:
    def synthesize(self, text: str, language: str):
        return np.ones(1, dtype=np.float32), 16000


@pytest.fixture(autouse=True)
def _clean_session():
    discussion_session.deactivate()
    yield
    discussion_session.deactivate()


def _loop(monkeypatch, dispatcher: CommandDispatcher, stt_texts: list[str]):
    loop = VoiceAssistantLoop(dispatcher)
    monkeypatch.setattr(
        pipeline_module.audio_io,
        "record_until_silence",
        lambda settings, stop_event, **kwargs: np.ones(1600, dtype=np.float32),
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(
        pipeline_module.profile_service_layer,
        "get_fact",
        lambda uow, key: "джарвис" if key == ASSISTANT_NAME_KEY else None,
    )
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    return loop, spoken, _FakeSTT(stt_texts)


def test_discussion_mode_buffers_speech_and_gives_an_opinion_on_the_code_phrase(monkeypatch) -> None:
    dispatched: list[str] = []

    async def noop(_p):
        dispatched.append("noop")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", noop, dangerous=False, description="")

    seen_transcripts: list[str] = []

    async def fake_build_opinion(transcript, assistant_name, language="ru"):
        seen_transcripts.append(transcript)
        return "Я склоняюсь к ипотеке."

    monkeypatch.setattr(pipeline_module.discussion_opinion, "build_opinion", fake_build_opinion)

    loop, spoken, stt = _loop(
        monkeypatch,
        dispatcher,
        [
            "давай подискутируем",
            "надо брать ипотеку прямо сейчас",
            "нет, лучше копить и снимать",
            "что думаешь, джарвис",
            "выйди из режима дискуссии",
        ],
    )

    result = loop._handle_command(stt, _FakeTTS())

    assert result is False
    assert dispatched == []  # nothing was ever classified as a command
    assert len(seen_transcripts) == 1
    assert "ипотеку" in seen_transcripts[0] and "копить" in seen_transcripts[0]
    assert any("Я склоняюсь к ипотеке." in line for line in spoken)
    assert any("Выхожу из режима дискуссии" in line for line in spoken)
    assert discussion_session.is_active() is False


def test_discussion_mode_ignores_normal_commands_until_exit(monkeypatch) -> None:
    executed: list[str] = []

    async def mute(_p):
        executed.append("mute")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")

    loop, spoken, stt = _loop(
        monkeypatch,
        dispatcher,
        ["режим дискуссии", "выключи звук", "поставь музыку", "выйди из режима дискуссии"],
    )

    loop._handle_command(stt, _FakeTTS())

    # "выключи звук" / "поставь музыку" were spoken *inside* discussion mode
    # and must not have been dispatched.
    assert executed == []
    assert discussion_session.is_active() is False


def test_discussion_mode_exits_on_the_stop_word(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop, spoken, stt = _loop(monkeypatch, dispatcher, ["давай подискутируем", "стоп"])

    result = loop._handle_command(stt, _FakeTTS())

    assert result is False
    assert discussion_session.is_active() is False
