from __future__ import annotations

from modules.messaging.domain import OutboundMessage
from modules.telegram_userbot import client_manager, outbound_poller


async def test_send_one_marks_delivered_when_a_connected_account_succeeds(monkeypatch) -> None:
    marked: list[tuple[int, bool]] = []

    monkeypatch.setattr(client_manager, "connected_account_ids", lambda: [1, 2])

    async def fake_send(account_id: int, recipient: str, text: str) -> bool:
        return account_id == 2

    monkeypatch.setattr(client_manager, "send_message", fake_send)
    monkeypatch.setattr(
        outbound_poller.messaging_service_layer,
        "mark_outbound_delivered",
        lambda uow, message_id, delivered: marked.append((message_id, delivered)),
    )

    message = OutboundMessage(id=7, source="telegram", recipient_identifier="someone", text="hi")
    await outbound_poller._send_one(message)

    assert marked == [(7, True)]


async def test_send_one_marks_failed_when_no_account_succeeds(monkeypatch) -> None:
    marked: list[tuple[int, bool]] = []

    monkeypatch.setattr(client_manager, "connected_account_ids", lambda: [1])

    async def fake_send(account_id: int, recipient: str, text: str) -> bool:
        return False

    monkeypatch.setattr(client_manager, "send_message", fake_send)
    monkeypatch.setattr(
        outbound_poller.messaging_service_layer,
        "mark_outbound_delivered",
        lambda uow, message_id, delivered: marked.append((message_id, delivered)),
    )

    message = OutboundMessage(id=8, source="telegram", recipient_identifier="someone", text="hi")
    await outbound_poller._send_one(message)

    assert marked == [(8, False)]


async def test_send_one_marks_failed_with_no_connected_accounts(monkeypatch) -> None:
    marked: list[tuple[int, bool]] = []

    monkeypatch.setattr(client_manager, "connected_account_ids", lambda: [])
    monkeypatch.setattr(
        outbound_poller.messaging_service_layer,
        "mark_outbound_delivered",
        lambda uow, message_id, delivered: marked.append((message_id, delivered)),
    )

    message = OutboundMessage(id=9, source="telegram", recipient_identifier="someone", text="hi")
    await outbound_poller._send_one(message)

    assert marked == [(9, False)]
