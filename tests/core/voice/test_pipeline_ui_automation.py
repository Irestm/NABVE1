from __future__ import annotations

import asyncio

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.ui_automation.domain import UIStep


def _make_loop(dispatcher: CommandDispatcher | None = None) -> VoiceAssistantLoop:
    return VoiceAssistantLoop(dispatcher or CommandDispatcher())


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


def _run_coro_directly(coro, barge_in, language):
    # Stands in for core.voice.interruption.run_cancellable in tests — see
    # tests/core/voice/test_pipeline_messaging.py's identical helper.
    return asyncio.run(coro)


def _patch_no_barge_in(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cancellable", _run_coro_directly)


_STEPS = [UIStep(action="press_key", key="Escape")]


def test_resolve_ui_action_dispatches_and_confirms_after_announcing(monkeypatch) -> None:
    # ui_action is registered dangerous=True (a click/type_text/press_key
    # sequence is full remote control of this machine's mouse/keyboard —
    # see modules/ui_automation/handlers.py's design notes), so the
    # resolver must dispatch() -> get CONFIRMATION_REQUIRED -> confirm()
    # itself, exactly like _resolve_messaging_reply already does for the
    # same reason, rather than handing a Command back for the generic
    # (blocking, content-free) confirmation flow to pick up.
    _patch_no_barge_in(monkeypatch)

    async def fake_ground(raw_text: str):
        assert raw_text == "нажми эскейп"
        return _STEPS

    monkeypatch.setattr(pipeline_module.ui_service_layer, "ground_instruction", fake_ground)
    monkeypatch.setattr(pipeline_module.ui_announce, "describe_steps", lambda steps, lang: "Нажимаю Escape.")

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("ui_action", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)

    spoken: list[str] = []
    monkeypatch.setattr(
        loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False
    )

    command = Command(name="ui_action", params={"raw_text": "нажми эскейп"})

    result, interrupted = loop._resolve_ui_action(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False
    # Announced first, then (after dispatch -> confirmation_required ->
    # confirm) the handler's own final response is spoken too.
    assert spoken == ["Нажимаю Escape.", "Готово."]
    assert executed == [{"steps": [{"action": "press_key", "key": "Escape"}], "announcement": "Нажимаю Escape."}]


def test_resolve_ui_action_does_not_dispatch_when_announcement_is_interrupted(monkeypatch) -> None:
    _patch_no_barge_in(monkeypatch)

    async def fake_ground(raw_text: str):
        return _STEPS

    monkeypatch.setattr(pipeline_module.ui_service_layer, "ground_instruction", fake_ground)
    monkeypatch.setattr(pipeline_module.ui_announce, "describe_steps", lambda steps, lang: "Нажимаю Escape.")

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("ui_action", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)

    # Barge-in cuts off the announcement itself.
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: True)

    command = Command(name="ui_action", params={"raw_text": "нажми эскейп"})

    result, interrupted = loop._resolve_ui_action(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is True
    assert executed == []  # never dispatched — the user interrupted before hearing what would happen


def test_resolve_ui_action_gives_up_when_grounding_finds_nothing(monkeypatch) -> None:
    _patch_no_barge_in(monkeypatch)

    async def fake_ground(raw_text: str):
        return None

    monkeypatch.setattr(pipeline_module.ui_service_layer, "ground_instruction", fake_ground)

    dispatcher = CommandDispatcher()
    loop = _make_loop(dispatcher)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command = Command(name="ui_action", params={"raw_text": "что-то невнятное"})

    result, interrupted = loop._resolve_ui_action(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False


def test_resolve_ui_action_dispatches_directly_when_not_registered_dangerous(monkeypatch) -> None:
    # Sanity check that the confirm() round-trip is conditional on the
    # dispatcher actually returning CONFIRMATION_REQUIRED, not hardcoded —
    # if a handler were registered dangerous=False, dispatch() alone would
    # already run it.
    _patch_no_barge_in(monkeypatch)

    async def fake_ground(raw_text: str):
        return _STEPS

    monkeypatch.setattr(pipeline_module.ui_service_layer, "ground_instruction", fake_ground)
    monkeypatch.setattr(pipeline_module.ui_announce, "describe_steps", lambda steps, lang: "Нажимаю Escape.")

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("ui_action", handler, dangerous=False, description="")
    loop = _make_loop(dispatcher)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command = Command(name="ui_action", params={"raw_text": "нажми эскейп"})

    result, interrupted = loop._resolve_ui_action(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False
    assert len(executed) == 1
