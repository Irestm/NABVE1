from __future__ import annotations

import asyncio

import numpy as np
import pytest

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.fitness_tracker import context_state as fitness_context_state
from modules.fitness_tracker.intent_parser import IntentCategory, ParsedIntent


@pytest.fixture(autouse=True)
def _reset_fitness_context() -> None:
    fitness_context_state.deactivate()
    yield
    fitness_context_state.deactivate()


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


# --- _resolve_active_fitness_context_utterance ------------------------------


def test_active_utterance_returns_none_when_context_is_off() -> None:
    loop = _make_loop()
    assert loop._resolve_active_fitness_context_utterance("я вешу 78", "ru") is None


def test_active_utterance_claims_any_text_when_context_is_on() -> None:
    fitness_context_state.activate()
    loop = _make_loop()

    command = loop._resolve_active_fitness_context_utterance("выключи компьютер", "ru")

    assert command == Command(name="fitness_utterance", params={"text": "выключи компьютер"})


# --- _resolve_fitness_activate -----------------------------------------------


def test_resolve_fitness_activate_turns_on_the_context_and_speaks(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    interrupted = loop._resolve_fitness_activate(tts=None, response_language="ru")

    assert interrupted is False
    assert fitness_context_state.is_active() is True
    assert spoken == [pipeline_module.fitness_announce.context_activated_text("ru")]


# --- _resolve_fitness_utterance: exit ----------------------------------------


def test_resolve_fitness_utterance_exit_phrase_deactivates(monkeypatch: pytest.MonkeyPatch) -> None:
    fitness_context_state.activate()
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="fitness_utterance", params={"text": "выйди из фитнес трекера"})
    interrupted = loop._resolve_fitness_utterance(command, tts=None, command_stt=None, response_language="ru")

    assert interrupted is False
    assert fitness_context_state.is_active() is False
    assert spoken == [pipeline_module.fitness_announce.context_deactivated_text("ru")]


# --- _resolve_fitness_utterance: off-topic -> chat ---------------------------


def test_resolve_fitness_utterance_routes_off_topic_speech_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    fitness_context_state.activate()
    monkeypatch.setattr(pipeline_module.fitness_intent_parser, "parse", lambda text: ParsedIntent(category=None))

    async def fake_answer_question(text: str, language: str) -> str:
        assert text == "какая сегодня погода"
        return "Не знаю, я не про погоду."

    monkeypatch.setattr(pipeline_module.fitness_chat, "answer_question", fake_answer_question)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="fitness_utterance", params={"text": "какая сегодня погода"})
    interrupted = loop._resolve_fitness_utterance(command, tts=None, command_stt=None, response_language="ru")

    assert interrupted is False
    assert spoken == ["Не знаю, я не про погоду."]


def test_resolve_fitness_utterance_chat_error_speaks_not_understood(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    fitness_context_state.activate()
    monkeypatch.setattr(pipeline_module.fitness_intent_parser, "parse", lambda text: ParsedIntent(category=None))

    async def fake_answer_question(text: str, language: str) -> str:
        raise pipeline_module.fitness_chat.FitnessChatError("недоступно")

    monkeypatch.setattr(pipeline_module.fitness_chat, "answer_question", fake_answer_question)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="fitness_utterance", params={"text": "вопрос"})
    loop._resolve_fitness_utterance(command, tts=None, command_stt=None, response_language="ru")

    assert spoken == [pipeline_module.not_understood("ru")]


# --- _resolve_fitness_utterance: fully-resolved intent -----------------------


def test_resolve_fitness_utterance_applies_a_complete_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    fitness_context_state.activate()
    parsed = ParsedIntent(category=IntentCategory.WEIGHT, entities={"weight_kg": 78.0})
    monkeypatch.setattr(pipeline_module.fitness_intent_parser, "parse", lambda text: parsed)

    async def fake_apply_intent(p: ParsedIntent, language: str) -> str:
        assert p is parsed
        return "Записал, твой вес теперь 78 килограмм."

    monkeypatch.setattr(pipeline_module.fitness_voice_commands, "apply_intent", fake_apply_intent)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="fitness_utterance", params={"text": "я сегодня вешу 78 кг"})
    interrupted = loop._resolve_fitness_utterance(command, tts=None, command_stt=None, response_language="ru")

    assert interrupted is False
    assert spoken == ["Записал, твой вес теперь 78 килограмм."]


# --- _resolve_fitness_utterance: clarify round -------------------------------


def test_resolve_fitness_utterance_clarifies_a_missing_field_then_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    _patch_no_recording(monkeypatch)
    fitness_context_state.activate()

    incomplete = ParsedIntent(category=IntentCategory.WEIGHT, entities={}, missing_fields=["weight_kg"])
    completed = ParsedIntent(category=IntentCategory.WEIGHT, entities={"weight_kg": 80.0})
    monkeypatch.setattr(pipeline_module.fitness_intent_parser, "parse", lambda text: incomplete)
    monkeypatch.setattr(pipeline_module.fitness_voice_commands, "clarify_question_text", lambda p, lang: "Уточни число.")
    monkeypatch.setattr(
        pipeline_module.fitness_voice_commands,
        "merge_followup",
        lambda p, followup: completed if followup == "80" else p,
    )

    async def fake_apply_intent(p: ParsedIntent, language: str) -> str:
        assert p is completed
        return "Записал, твой вес теперь 80 килограмм."

    monkeypatch.setattr(pipeline_module.fitness_voice_commands, "apply_intent", fake_apply_intent)

    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    command_stt = _FakeSTT(["80"])

    command = Command(name="fitness_utterance", params={"text": "запиши вес"})
    interrupted = loop._resolve_fitness_utterance(command, tts=None, command_stt=command_stt, response_language="ru")

    assert interrupted is False
    assert spoken == ["Уточни число.", "Записал, твой вес теперь 80 килограмм."]


def test_resolve_fitness_utterance_gives_up_when_clarification_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    _patch_no_recording(monkeypatch)
    fitness_context_state.activate()

    incomplete = ParsedIntent(category=IntentCategory.WEIGHT, entities={}, missing_fields=["weight_kg"])
    monkeypatch.setattr(pipeline_module.fitness_intent_parser, "parse", lambda text: incomplete)
    monkeypatch.setattr(pipeline_module.fitness_voice_commands, "clarify_question_text", lambda p, lang: "Уточни число.")
    monkeypatch.setattr(pipeline_module.fitness_voice_commands, "merge_followup", lambda p, followup: p)

    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)
    command_stt = _FakeSTT(["не знаю"])

    command = Command(name="fitness_utterance", params={"text": "запиши вес"})
    interrupted = loop._resolve_fitness_utterance(command, tts=None, command_stt=command_stt, response_language="ru")

    assert interrupted is False
    assert spoken == ["Уточни число.", pipeline_module.not_understood("ru")]
