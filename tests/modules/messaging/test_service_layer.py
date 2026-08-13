from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from core.message_bus import MessageBus
from modules.messaging import service_layer
from modules.messaging.domain import PendingMessageStatus
from modules.messaging.events import MessageReceived
from modules.messaging.uow import MessagingUnitOfWork


def _uow(tmp_path) -> MessagingUnitOfWork:
    return MessagingUnitOfWork(tmp_path / "assistant.db")


def test_record_incoming_message_ignores_unwatched_sender(tmp_path) -> None:
    uow = _uow(tmp_path)
    result = service_layer.record_incoming_message(uow, "telegram", "@stranger", "Stranger", "hi")
    assert result is None
    assert service_layer.list_pending(uow) == []


def test_record_incoming_message_creates_pending_for_watched_sender(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira", note="сестра")

    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")

    assert pending is not None
    assert pending.status == PendingMessageStatus.PENDING
    assert [m.id for m in service_layer.list_pending(uow)] == [pending.id]


def test_identifier_matching_normalizes_at_sign_and_case(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@Ira")

    pending = service_layer.record_incoming_message(uow, "telegram", "IRA", "Ира", "привет")

    assert pending is not None


def test_record_incoming_message_merges_into_existing_pending(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    first = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")
    second = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "как дела?")

    assert second is not None
    assert second.id == first.id
    assert second.text == "привет\nкак дела?"
    assert len(service_layer.list_pending(uow)) == 1


def test_record_incoming_message_bumps_snoozed_back_to_pending(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    first = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")
    assert service_layer.snooze(uow, first.id, 30) is True
    assert service_layer.list_pending(uow) == []  # snoozed, not pending

    second = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "ты тут?")

    assert second is not None
    assert second.id == first.id
    assert second.status == PendingMessageStatus.PENDING
    assert second.snooze_until is None
    assert second.text == "привет\nты тут?"
    assert [m.id for m in service_layer.list_pending(uow)] == [first.id]


def test_mark_replied(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")

    assert service_layer.mark_replied(uow, pending.id) is True
    assert service_layer.list_pending(uow) == []
    assert service_layer.mark_replied(uow, 9999) is False


def test_snooze_unknown_message_returns_false(tmp_path) -> None:
    uow = _uow(tmp_path)
    assert service_layer.snooze(uow, 9999, 10) is False


def test_notify_new_message_publishes_message_received(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")

    bus = MessageBus()
    received: list[MessageReceived] = []

    async def handler(event: MessageReceived) -> None:
        received.append(event)

    bus.subscribe(MessageReceived, handler)
    asyncio.run(service_layer.notify_new_message(bus, pending))

    assert len(received) == 1
    assert received[0].message_id == pending.id
    assert received[0].sender_label == "Ира"
    assert received[0].text == "привет"


def test_check_due_snoozes_flips_status_and_publishes(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")
    service_layer.snooze(uow, pending.id, 10)

    bus = MessageBus()
    received: list[MessageReceived] = []

    async def handler(event: MessageReceived) -> None:
        received.append(event)

    bus.subscribe(MessageReceived, handler)

    future_now = datetime.now() + timedelta(minutes=20)
    count = asyncio.run(service_layer.check_due_snoozes(uow, bus, now=future_now))

    assert count == 1
    assert len(received) == 1
    assert received[0].message_id == pending.id
    assert [m.status for m in [service_layer.list_pending(uow)[0]]] == [PendingMessageStatus.PENDING]


def test_check_due_snoozes_ignores_not_yet_due(tmp_path) -> None:
    uow = _uow(tmp_path)
    service_layer.add_watched_contact(uow, "telegram", "@ira")
    pending = service_layer.record_incoming_message(uow, "telegram", "@ira", "Ира", "привет")
    service_layer.snooze(uow, pending.id, 60)

    bus = MessageBus()
    count = asyncio.run(service_layer.check_due_snoozes(uow, bus, now=datetime.now()))

    assert count == 0
    assert service_layer.list_pending(uow) == []
