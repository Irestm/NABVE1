from __future__ import annotations

from datetime import datetime

import pytest

from modules.calendar import notification_adapter
from modules.calendar.events import ReminderDue


def test_notify_linux_requires_notify_send(monkeypatch) -> None:
    monkeypatch.setattr(notification_adapter.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notification_adapter.shutil, "which", lambda _cmd: None)

    with pytest.raises(RuntimeError, match="notify-send"):
        notification_adapter.notify("title", "message")


def test_notify_linux_invokes_notify_send(monkeypatch) -> None:
    monkeypatch.setattr(notification_adapter.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notification_adapter.shutil, "which", lambda _cmd: "/usr/bin/notify-send")
    calls = []
    monkeypatch.setattr(notification_adapter.subprocess, "run", lambda *a, **k: calls.append((a, k)))

    notification_adapter.notify("title", "message")

    assert calls[0][0] == (["notify-send", "title", "message"],)


def test_notify_unsupported_platform_raises(monkeypatch) -> None:
    monkeypatch.setattr(notification_adapter.platform, "system", lambda: "Plan9")

    with pytest.raises(RuntimeError, match="Plan9"):
        notification_adapter.notify("title", "message")


async def test_send_desktop_notification_swallows_notify_failure(monkeypatch) -> None:
    def _boom(_title: str, _message: str) -> None:
        raise RuntimeError("no notify-send")

    monkeypatch.setattr(notification_adapter, "notify", _boom)
    event = ReminderDue(event_id=1, title="Meeting", event_time=datetime(2030, 1, 1))

    await notification_adapter.send_desktop_notification(event)  # must not raise


async def test_send_desktop_notification_calls_notify_with_event_title(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(notification_adapter, "notify", lambda title, message: calls.append((title, message)))
    event = ReminderDue(event_id=1, title="Meeting", event_time=datetime(2030, 1, 1))

    await notification_adapter.send_desktop_notification(event)

    assert calls == [("Calendar reminder", "Meeting")]
