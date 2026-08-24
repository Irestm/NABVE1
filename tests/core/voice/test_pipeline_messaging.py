from __future__ import annotations

import asyncio

import numpy as np

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.stt import TranscriptionResult
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.uow import MessagingUnitOfWork


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


class _FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)

    def transcribe(self, audio, language=None) -> TranscriptionResult:
        return TranscriptionResult(text=next(self._texts), detected_language="ru", language_probability=0.99)


def _run_coro_directly(coro, barge_in, language):
    # Stands in for core.voice.interruption.run_cancellable in tests — runs
    # the coroutine straight through with no real BargeInMonitor/mic
    # involvement, since these tests care about the resolver logic, not
    # barge-in itself (see tests/core/voice/test_interruption.py and
    # test_pipeline_interruption.py for dedicated cancellation coverage).
    return asyncio.run(coro)


def _patch_no_barge_in(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cancellable", _run_coro_directly)


# --- _resolve_messaging_watch_contact ---------------------------------------


def test_resolve_watch_contact_strips_telegram_suffix(monkeypatch) -> None:
    loop = _make_loop()
    command = Command(name="messaging_watch_contact", params={"raw_text": "ira в телеграме"})

    resolved, interrupted = loop._resolve_messaging_watch_contact(command, tts=None, response_language="ru")

    assert interrupted is False
    assert resolved == Command(
        name="messaging_watch_contact", params={"source": "telegram", "identifier": "ira"}
    )


def test_resolve_watch_contact_strips_gmail_suffix(monkeypatch) -> None:
    loop = _make_loop()
    command = Command(name="messaging_watch_contact", params={"raw_text": "ira@example.com на почте"})

    resolved, interrupted = loop._resolve_messaging_watch_contact(command, tts=None, response_language="ru")

    assert interrupted is False
    assert resolved == Command(
        name="messaging_watch_contact", params={"source": "gmail", "identifier": "ira@example.com"}
    )


def test_resolve_watch_contact_strips_in_gmail_suffix(monkeypatch) -> None:
    loop = _make_loop()
    command = Command(name="messaging_watch_contact", params={"raw_text": "ira@example.com in gmail"})

    resolved, _ = loop._resolve_messaging_watch_contact(command, tts=None, response_language="ru")

    assert resolved.params == {"source": "gmail", "identifier": "ira@example.com"}


def test_resolve_watch_contact_without_suffix(monkeypatch) -> None:
    loop = _make_loop()
    command = Command(name="messaging_watch_contact", params={"raw_text": "ira"})

    resolved, _ = loop._resolve_messaging_watch_contact(command, tts=None, response_language="ru")

    assert resolved.params == {"source": "telegram", "identifier": "ira"}


def test_resolve_watch_contact_empty_gives_up(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    command = Command(name="messaging_watch_contact", params={"raw_text": ""})

    resolved, interrupted = loop._resolve_messaging_watch_contact(command, tts=None, response_language="ru")

    assert resolved is None
    assert interrupted is False


# --- _resolve_pending_message_target -----------------------------------------


def _uow_factory(tmp_path):
    def factory() -> MessagingUnitOfWork:
        return MessagingUnitOfWork(tmp_path / "assistant.db")

    return factory


def test_resolve_target_no_pending_speaks_and_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", _uow_factory(tmp_path))
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    target, interrupted = loop._resolve_pending_message_target("", tts=None, command_stt=None, response_language="ru")

    assert target is None
    assert interrupted is False
    assert spoken == ["Нет ожидающих сообщений."]


def test_resolve_target_single_pending_needs_no_question(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "ira", "Ира", "привет")

    loop = _make_loop()

    def fail_if_spoken(tts, text, language):
        raise AssertionError("should not need to ask anything with only one pending message")

    monkeypatch.setattr(loop, "_speak_safely", fail_if_spoken)

    target, interrupted = loop._resolve_pending_message_target(
        "", tts=None, command_stt=None, response_language="ru"
    )

    assert interrupted is False
    assert target.id == pending.id


def test_resolve_target_raw_target_disambiguates_without_asking(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "dima")
    ira_msg = messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "ira", "Ира", "привет")
    messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "dima", "Дима", "привет")

    loop = _make_loop()

    def fail_if_spoken(tts, text, language):
        raise AssertionError("should not need to ask when raw_target already disambiguates")

    monkeypatch.setattr(loop, "_speak_safely", fail_if_spoken)

    target, interrupted = loop._resolve_pending_message_target(
        "ира", tts=None, command_stt=None, response_language="ru"
    )

    assert interrupted is False
    assert target.id == ira_msg.id


def test_resolve_target_multiple_pending_asks_who_and_matches_answer(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "dima")
    messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "ira", "Ира", "привет")
    dima_msg = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "dima", "Дима", "привет"
    )

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    target, interrupted = loop._resolve_pending_message_target(
        "", tts=None, command_stt=_FakeSTT(["дима"]), response_language="ru"
    )

    assert interrupted is False
    assert target.id == dima_msg.id


# --- _resolve_messaging_reply -------------------------------------------------


def test_resolve_messaging_reply_full_flow_sends_and_marks_replied(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет"
    )

    _patch_no_barge_in(monkeypatch)

    async def fake_clean(raw_text: str) -> str:
        assert raw_text == "привет как дела"
        return "Привет! Как дела?"

    monkeypatch.setattr(pipeline_module.messaging_text_cleanup, "clean_dictated_text", fake_clean)

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Отправлено."}

    dispatcher = CommandDispatcher()
    dispatcher.register("messaging_reply", handler, dangerous=True, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="messaging_reply", params={"raw_target": ""})
    command_stt = _FakeSTT(["привет как дела", "да отправляй"])

    result, interrupted = loop._resolve_messaging_reply(
        command, command_stt, tts=None, response_language="ru", spoken_language="ru"
    )

    assert result is None
    assert interrupted is False
    # Note: this test's dispatcher handler is a fake standing in for
    # modules.messaging.handlers._handle_reply, so it deliberately doesn't
    # exercise mark_replied/send_message itself — that's covered by
    # tests/modules/messaging/test_handlers.py. What this test verifies is
    # the resolver's own confirmation sequencing: dispatch() -> (dangerous,
    # so CONFIRMATION_REQUIRED) -> confirm() -> handler actually runs, with
    # the cleaned text, resolved message_id, and the received_at snapshot
    # _handle_reply uses to detect a message merging in mid-conversation
    # (see modules/messaging/handlers.py's own race-guard comment).
    assert executed == [
        {
            "message_id": pending.id,
            "text": "Привет! Как дела?",
            "expected_received_at": pending.received_at.isoformat(),
        }
    ]


def test_resolve_messaging_reply_declines_when_answer_is_negative(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет"
    )

    _patch_no_barge_in(monkeypatch)

    async def fake_clean(raw_text: str) -> str:
        return raw_text

    monkeypatch.setattr(pipeline_module.messaging_text_cleanup, "clean_dictated_text", fake_clean)

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Отправлено."}

    dispatcher = CommandDispatcher()
    dispatcher.register("messaging_reply", handler, dangerous=True, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="messaging_reply", params={"raw_target": ""})
    command_stt = _FakeSTT(["привет", "нет отмена"])

    result, interrupted = loop._resolve_messaging_reply(
        command, command_stt, tts=None, response_language="ru", spoken_language="ru"
    )

    assert result is None
    assert executed == []  # never sent
    assert [m.id for m in messaging_service_layer.list_pending(uow_factory())] == [pending.id]  # still pending


# --- _resolve_messaging_snooze -------------------------------------------------


def test_resolve_messaging_snooze_with_inline_duration_asks_nothing(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет"
    )

    loop = _make_loop()

    def fail_if_spoken(tts, text, language):
        raise AssertionError("duration was already inline, should not need to ask")

    monkeypatch.setattr(loop, "_speak_safely", fail_if_spoken)

    command = Command(name="messaging_snooze", params={"raw_text": "на 10 минут"})
    result, interrupted = loop._resolve_messaging_snooze(command, command_stt=None, tts=None, response_language="ru")

    assert interrupted is False
    assert result == Command(name="messaging_snooze", params={"message_id": pending.id, "minutes": 10})


def test_resolve_messaging_snooze_asks_for_duration_when_missing(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет"
    )

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="messaging_snooze", params={"raw_text": ""})
    command_stt = _FakeSTT(["полчаса"])

    result, interrupted = loop._resolve_messaging_snooze(command, command_stt, tts=None, response_language="ru")

    assert interrupted is False
    assert result == Command(name="messaging_snooze", params={"message_id": pending.id, "minutes": 30})


def test_resolve_messaging_snooze_gives_up_when_duration_never_parses(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "ira", "Ира", "привет")

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="messaging_snooze", params={"raw_text": ""})
    command_stt = _FakeSTT(["не знаю"])

    result, interrupted = loop._resolve_messaging_snooze(command, command_stt, tts=None, response_language="ru")

    assert result is None


# --- _resolve_edit_pending_message -------------------------------------------


def test_resolve_edit_pending_message_asks_for_instruction(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет, как дела"
    )

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="edit_pending_message", params={"raw_target": "ira"})
    command_stt = _FakeSTT(["сделай короче"])

    result, interrupted = loop._resolve_edit_pending_message(command, command_stt, tts=None, response_language="ru")

    assert interrupted is False
    assert result == Command(
        name="edit_pending_message", params={"message_id": pending.id, "instruction": "сделай короче"}
    )


def test_resolve_edit_pending_message_gives_up_on_an_empty_instruction(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    messaging_service_layer.record_incoming_message(uow_factory(), "telegram", "ira", "Ира", "привет")

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )

    command = Command(name="edit_pending_message", params={"raw_target": "ira"})
    command_stt = _FakeSTT([""])

    result, interrupted = loop._resolve_edit_pending_message(command, command_stt, tts=None, response_language="ru")

    assert result is None


def test_resolve_edit_pending_message_returns_none_when_nothing_pending(tmp_path, monkeypatch) -> None:
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)

    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command = Command(name="edit_pending_message", params={"raw_target": ""})

    result, interrupted = loop._resolve_edit_pending_message(command, command_stt=None, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False


# --- _handle_command: "ответь"/"отложи" with nothing pending falls through to AI ---


def test_handle_command_falls_through_to_ai_when_nothing_is_pending(tmp_path, monkeypatch) -> None:
    """Regression: interpret() matches ANY utterance starting with
    "ответь"/"отложи" (see core/voice/intent.py's
    _MESSAGING_REPLY_PATTERNS/_MESSAGING_SNOOZE_PATTERNS), including
    ordinary free-text speech that has nothing to do with a watched
    contact's message ("ответь, который час"). Without a pending-message
    check, _handle_command used to commit to the messaging_reply resolver
    regardless and dead-end on "Нет ожидающих сообщений." instead of ever
    reaching the AI classifier that would have actually answered."""
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    # No add_watched_contact / record_incoming_message call: the pending
    # table is empty, same as any user who has never used messaging_watch.

    dispatcher = CommandDispatcher()
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)
    # Isolates this test from whichever plugins happen to be registered in
    # modules.plugin_agent.plugin_loader's global registry by the time the
    # suite runs (e.g. a real "current time" plugin can fuzzy-match "который
    # час") — this test is only about the messaging pending-check fallback,
    # not plugin matching.
    monkeypatch.setattr(pipeline_module, "match_plugin_command", lambda text: None)

    ai_calls: list[str] = []

    def fake_classify(text, command_stt, tts, response_language):
        ai_calls.append(text)
        return None, False

    monkeypatch.setattr(loop, "_classify_via_ai_bridge", fake_classify)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command_stt = _FakeSTT(["ответь который час"])
    loop._handle_command(command_stt, tts=None)

    assert ai_calls == ["ответь который час"]


def test_handle_command_still_uses_messaging_flow_when_something_is_pending(tmp_path, monkeypatch) -> None:
    """Same trigger phrase as above, but with an actual pending message —
    must still route into the messaging_reply resolver, not the AI
    fallback, so the fix above doesn't regress the real feature."""
    uow_factory = _uow_factory(tmp_path)
    monkeypatch.setattr(pipeline_module, "MessagingUnitOfWork", uow_factory)
    messaging_service_layer.add_watched_contact(uow_factory(), "telegram", "ira")
    pending = messaging_service_layer.record_incoming_message(
        uow_factory(), "telegram", "ira", "Ира", "привет"
    )

    _patch_no_barge_in(monkeypatch)

    async def fake_clean(raw_text: str) -> str:
        return raw_text

    monkeypatch.setattr(pipeline_module.messaging_text_cleanup, "clean_dictated_text", fake_clean)

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Отправлено."}

    dispatcher = CommandDispatcher()
    dispatcher.register("messaging_reply", handler, dangerous=True, description="")
    loop = VoiceAssistantLoop(dispatcher)

    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: np.ones(1, dtype=np.float32)
    )
    monkeypatch.setattr(loop, "_learn_facts", lambda text, language: None)

    ai_calls: list[str] = []
    monkeypatch.setattr(
        loop,
        "_classify_via_ai_bridge",
        lambda text, command_stt, tts, response_language: (ai_calls.append(text), (None, False))[1],
    )

    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    # ["ответь ире", "привет", "да отправляй"]: initial command, dictated
    # reply, then the yes/no confirmation — three STT passes, same as any
    # full messaging_reply turn through _handle_command.
    command_stt = _FakeSTT(["ответь ире", "привет", "да отправляй"])
    loop._handle_command(command_stt, tts=None)

    assert ai_calls == []
    assert spoken[0] == "Что ответить?"
    assert executed == [
        {
            "message_id": pending.id,
            "text": "привет",
            "expected_received_at": pending.received_at.isoformat(),
        }
    ]
