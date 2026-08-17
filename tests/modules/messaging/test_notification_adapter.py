from __future__ import annotations

from datetime import datetime

from modules.messaging import notification_adapter
from modules.messaging.events import MessageReceived


async def test_send_desktop_notification_swallows_notify_failure(monkeypatch) -> None:
    def _boom(_title: str, _message: str) -> None:
        raise RuntimeError("no notify-send")

    monkeypatch.setattr(notification_adapter, "notify", _boom)
    event = MessageReceived(
        message_id=1, source="telegram", sender_label="Ира", text="Привет", received_at=datetime(2030, 1, 1)
    )

    await notification_adapter.send_desktop_notification(event)  # must not raise


async def test_send_desktop_notification_calls_notify_with_sender_and_text(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(notification_adapter, "notify", lambda title, message: calls.append((title, message)))
    event = MessageReceived(
        message_id=1, source="telegram", sender_label="Ира", text="Привет", received_at=datetime(2030, 1, 1)
    )

    await notification_adapter.send_desktop_notification(event)

    assert calls == [("Сообщение от Ира", "Привет")]
