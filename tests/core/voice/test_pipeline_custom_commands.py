from __future__ import annotations

from datetime import datetime

import numpy as np

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.custom_commands.domain import ActionType, CustomCommand


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


class _FakeTTS:
    def synthesize(self, text: str, language: str):
        return np.ones(1, dtype=np.float32), 16000


def _direct_command(command_id: str = "abc123") -> CustomCommand:
    return CustomCommand(
        id=command_id,
        trigger_phrase="открой помойку",
        action_type=ActionType.OPEN_LINK,
        action_payload={"url": "https://example.com"},
        created_at=datetime.now(),
    )


def _instruction_command(command_id: str = "txt1") -> CustomCommand:
    return CustomCommand(
        id=command_id,
        trigger_phrase="напиши маме",
        action_type=ActionType.TEXT_INSTRUCTION,
        action_payload={"instruction": "напиши в телеграм маме что я задержусь"},
        created_at=datetime.now(),
    )


def _launch_app_command(command_id: str = "app1") -> CustomCommand:
    return CustomCommand(
        id=command_id,
        trigger_phrase="запусти игру",
        action_type=ActionType.LAUNCH_APP,
        action_payload={"executable_path": "/opt/game/run.sh"},
        created_at=datetime.now(),
    )


def _base_setup(monkeypatch, loop: VoiceAssistantLoop) -> None:
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)


def test_custom_command_matched_before_interpret_is_even_called(monkeypatch) -> None:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {"message": "готово"}

    dispatcher = CommandDispatcher()
    dispatcher.register("custom_abc123", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)
    _base_setup(monkeypatch, loop)

    def fail_interpret(text, language):
        raise AssertionError("interpret() must not be called when a custom command already matched")

    monkeypatch.setattr(pipeline_module, "interpret", fail_interpret)
    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _direct_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: False)
    monkeypatch.setattr(pipeline_module.custom_commands, "dispatcher_command_name", lambda cid: f"custom_{cid}")

    loop._handle_command(_FakeSTT(["открой помойку"]), _FakeTTS())

    assert executed == ["ran"]


def test_text_instruction_substitutes_stored_text_into_interpret(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)
    _base_setup(monkeypatch, loop)

    seen_texts: list[str] = []

    def fake_interpret(text, language):
        seen_texts.append(text)
        return None

    monkeypatch.setattr(pipeline_module, "interpret", fake_interpret)
    monkeypatch.setattr(pipeline_module, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(pipeline_module.command_classifier, "match_system_command", lambda text: None)
    monkeypatch.setattr(
        loop, "_classify_via_ai_bridge", lambda text, command_stt, tts, response_language: (None, False)
    )
    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _instruction_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: False)

    loop._handle_command(_FakeSTT(["напиши маме"]), _FakeTTS())

    assert seen_texts == ["напиши в телеграм маме что я задержусь"]


def test_text_instruction_asks_for_confirmation_when_enabled_and_declined(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)

    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    def fail_interpret(text, language):
        raise AssertionError("declined confirmation must never reach interpret()")

    monkeypatch.setattr(pipeline_module, "interpret", fail_interpret)
    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _instruction_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: True)

    loop._handle_command(_FakeSTT(["напиши маме", "нет"]), _FakeTTS())

    assert spoken[0] == "Выполнить «напиши маме»?"
    assert "не выполняю" in spoken[1]


def test_text_instruction_confirmed_then_substitutes(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)
    _base_setup(monkeypatch, loop)

    seen_texts: list[str] = []
    monkeypatch.setattr(pipeline_module, "interpret", lambda text, language: seen_texts.append(text) or None)
    monkeypatch.setattr(pipeline_module, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(pipeline_module.command_classifier, "match_system_command", lambda text: None)
    monkeypatch.setattr(
        loop, "_classify_via_ai_bridge", lambda text, command_stt, tts, response_language: (None, False)
    )
    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _instruction_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: True)

    loop._handle_command(_FakeSTT(["напиши маме", "да"]), _FakeTTS())

    assert seen_texts == ["напиши в телеграм маме что я задержусь"]


def test_launch_app_runs_immediately_when_confirmation_not_required(monkeypatch) -> None:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {"message": "готово"}

    dispatcher = CommandDispatcher()
    dispatcher.register("custom_app1", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)
    _base_setup(monkeypatch, loop)

    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _launch_app_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: False)
    monkeypatch.setattr(pipeline_module.custom_commands, "dispatcher_command_name", lambda cid: f"custom_{cid}")

    loop._handle_command(_FakeSTT(["запусти игру"]), _FakeTTS())

    assert executed == ["ran"]


def test_launch_app_asks_for_confirmation_when_enabled_and_approved(monkeypatch) -> None:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {"message": "готово"}

    dispatcher = CommandDispatcher()
    dispatcher.register("custom_app1", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event, **kwargs: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _launch_app_command())
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: True)
    monkeypatch.setattr(pipeline_module.custom_commands, "dispatcher_command_name", lambda cid: f"custom_{cid}")

    loop._handle_command(_FakeSTT(["запусти игру", "да"]), _FakeTTS())

    assert executed == ["ran"]


def test_open_link_custom_command_is_never_gated_by_confirmation_setting(monkeypatch) -> None:
    # Only launch_app/text_instruction are gated - see
    # core/voice/pipeline.py's _handle_command comment.
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("ran")
        return {"message": "готово"}

    dispatcher = CommandDispatcher()
    dispatcher.register("custom_abc123", handler, dangerous=False, description="")
    loop = VoiceAssistantLoop(dispatcher)
    _base_setup(monkeypatch, loop)

    monkeypatch.setattr(pipeline_module.custom_commands, "match", lambda text: _direct_command())
    # Confirmation is enabled globally, but open_link must still run
    # immediately with no spoken question.
    monkeypatch.setattr(pipeline_module.custom_commands, "requires_confirmation", lambda: True)
    monkeypatch.setattr(pipeline_module.custom_commands, "dispatcher_command_name", lambda cid: f"custom_{cid}")

    loop._handle_command(_FakeSTT(["открой помойку"]), _FakeTTS())

    assert executed == ["ran"]
