from __future__ import annotations

import asyncio

import pytest

import modules.messaging.handlers as handlers
from core.dispatcher import CommandDispatcher
from modules.messaging import service_layer
from modules.messaging.uow import MessagingUnitOfWork


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "assistant.db"
    monkeypatch.setattr(handlers, "MessagingUnitOfWork", lambda: MessagingUnitOfWork(db_path))


def test_watch_contact_then_list_watched(monkeypatch) -> None:
    result = asyncio.run(handlers._handle_watch_contact({"identifier": "@ira", "note": "сестра"}))
    assert result["identifier"] == "@ira"

    listed = asyncio.run(handlers._handle_list_watched({}))
    assert listed["contacts"][0]["identifier"] == "ira"  # normalized, no leading @
    assert "ira" in listed["message"]


def test_watch_contact_missing_identifier_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_watch_contact({}))


def test_watch_contact_rejects_a_bare_cyrillic_name_for_telegram() -> None:
    """Regression: a spoken "следи за Ирой" that never resolved to a real
    @username used to be accepted silently and then just never match any
    incoming message (modules/telegram/watcher.py's sender_identifier is
    always a real username or numeric id, never a spoken display name) —
    with no error telling the user why. A Cyrillic identifier can never be
    a real Telegram username, so this should fail loudly instead."""
    with pytest.raises(ValueError, match="username"):
        asyncio.run(handlers._handle_watch_contact({"identifier": "Ирой"}))


def test_watch_contact_accepts_a_phone_number_for_telegram() -> None:
    result = asyncio.run(handlers._handle_watch_contact({"identifier": "+79161234567"}))
    assert result["identifier"] == "+79161234567"


def test_watch_contact_cyrillic_identifier_still_allowed_for_gmail() -> None:
    # The ASCII/no-space check only applies to telegram — a Gmail address's
    # local part is always ASCII anyway, but the source-gated check must
    # not accidentally reject non-telegram sources.
    result = asyncio.run(
        handlers._handle_watch_contact({"identifier": "ира@example.com", "source": "gmail"})
    )
    assert result["identifier"] == "ира@example.com"


def test_reply_queues_outbound_message_and_marks_replied() -> None:
    asyncio.run(handlers._handle_watch_contact({"identifier": "@ira"}))
    db_path_uow = handlers.MessagingUnitOfWork()
    pending = service_layer.record_incoming_message(db_path_uow, "telegram", "@ira", "Ира", "привет")
    assert pending is not None

    result = asyncio.run(handlers._handle_reply({"message_id": pending.id, "text": "привет!"}))

    assert result["message_id"] == pending.id
    assert service_layer.list_pending(db_path_uow) == []  # marked replied, no longer pending
    queued = service_layer.list_pending_outbound(db_path_uow)
    assert len(queued) == 1
    assert queued[0].recipient_identifier == "ira"
    assert queued[0].text == "привет!"


def test_reply_to_gmail_source_raises() -> None:
    asyncio.run(handlers._handle_watch_contact({"identifier": "ira@example.com", "source": "gmail"}))
    uow = handlers.MessagingUnitOfWork()
    pending = service_layer.record_incoming_message(uow, "gmail", "ira@example.com", "Ира", "привет")
    assert pending is not None

    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_reply({"message_id": pending.id, "text": "привет!"}))
    # Still pending — the rejected reply attempt must not mark it replied.
    assert len(service_layer.list_pending(uow)) == 1


def test_reply_unknown_message_id_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_reply({"message_id": 9999, "text": "hi"}))


def test_reply_missing_params_raise() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_reply({"text": "hi"}))
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_reply({"message_id": 1}))


def test_snooze_pending_message(monkeypatch) -> None:
    asyncio.run(handlers._handle_watch_contact({"identifier": "@ira"}))
    uow = handlers.MessagingUnitOfWork()
    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")

    result = asyncio.run(handlers._handle_snooze({"message_id": pending.id, "minutes": 15}))

    assert result == {"message_id": pending.id, "minutes": 15, "message": "Отложено на 15 мин."}
    assert service_layer.list_pending(uow) == []


def test_snooze_unknown_message_id_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_snooze({"message_id": 9999, "minutes": 10}))


def test_register_commands_registers_all_four() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)
    names = {c.name for c in dispatcher.list_commands()}
    assert names == {
        "messaging_watch_contact",
        "messaging_list_watched",
        "messaging_reply",
        "messaging_snooze",
    }
    dangerous = {c.name for c in dispatcher.list_commands() if c.dangerous}
    assert dangerous == {"messaging_reply"}
