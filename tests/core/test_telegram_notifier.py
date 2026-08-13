from __future__ import annotations

import dataclasses
from datetime import datetime

import httpx

from core.config import Settings
from core.telegram_notifier import TelegramNotifier
from modules.calendar.events import ReminderDue
from modules.hardware_adaptive.events import HardwareAlertRaised
from modules.plugin_agent.events import PluginCandidateReadyForReview


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"telegram_notify_bot_token": None, "telegram_notify_chat_id": None}
    defaults.update(overrides)
    return dataclasses.replace(Settings(), **defaults)


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    """Records every POST it's asked to make; install via
    monkeypatch.setattr(httpx, "AsyncClient", ...) — used as a context
    manager exactly like the real httpx.AsyncClient is in
    core/telegram_notifier.py::TelegramNotifier._send."""

    instances: list["_FakeAsyncClient"] = []

    def __init__(self, **kwargs: object) -> None:
        self.requests: list[dict] = []
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: dict) -> _FakeResponse:
        self.requests.append({"url": url, "json": json})
        return _FakeResponse()


def _install_fake_client(monkeypatch) -> _FakeAsyncClient:
    _FakeAsyncClient.instances = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


async def test_does_nothing_when_not_configured(monkeypatch) -> None:
    fake_cls = _install_fake_client(monkeypatch)
    notifier = TelegramNotifier(_settings())

    await notifier.handle_reminder(ReminderDue(event_id=1, title="Позвонить маме", event_time=datetime.now()))

    assert fake_cls.instances == []  # never even constructed a client


async def test_sends_reminder_notification_when_configured(monkeypatch) -> None:
    fake_cls = _install_fake_client(monkeypatch)
    notifier = TelegramNotifier(_settings(telegram_notify_bot_token="123:abc", telegram_notify_chat_id="42"))

    await notifier.handle_reminder(ReminderDue(event_id=1, title="Позвонить маме", event_time=datetime.now()))

    requests = fake_cls.instances[0].requests
    assert len(requests) == 1
    assert requests[0]["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert requests[0]["json"]["chat_id"] == "42"
    assert "Позвонить маме" in requests[0]["json"]["text"]


async def test_sends_hardware_alert_notification(monkeypatch) -> None:
    fake_cls = _install_fake_client(monkeypatch)
    notifier = TelegramNotifier(_settings(telegram_notify_bot_token="123:abc", telegram_notify_chat_id="42"))

    await notifier.handle_hardware_alert(
        HardwareAlertRaised(metric="battery", severity="warning", message="Батарея разряжена", value=10.0)
    )

    assert "Батарея разряжена" in fake_cls.instances[0].requests[0]["json"]["text"]


async def test_plugin_candidate_notification_mentions_manual_review(monkeypatch) -> None:
    fake_cls = _install_fake_client(monkeypatch)
    notifier = TelegramNotifier(_settings(telegram_notify_bot_token="123:abc", telegram_notify_chat_id="42"))

    await notifier.handle_plugin_candidate(
        PluginCandidateReadyForReview(candidate_id=1, plugin_name="plugin_x", requires_manual_review=True)
    )

    text = fake_cls.instances[0].requests[0]["json"]["text"]
    assert "plugin_x" in text
    assert "ручной обзор" in text


async def test_plugin_candidate_notification_omits_review_note_when_not_flagged(monkeypatch) -> None:
    fake_cls = _install_fake_client(monkeypatch)
    notifier = TelegramNotifier(_settings(telegram_notify_bot_token="123:abc", telegram_notify_chat_id="42"))

    await notifier.handle_plugin_candidate(
        PluginCandidateReadyForReview(candidate_id=1, plugin_name="plugin_y", requires_manual_review=False)
    )

    assert "ручной обзор" not in fake_cls.instances[0].requests[0]["json"]["text"]


async def test_send_failure_is_caught_and_does_not_raise(monkeypatch) -> None:
    class _RaisingClient(_FakeAsyncClient):
        async def post(self, url: str, json: dict):
            raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "AsyncClient", _RaisingClient)
    notifier = TelegramNotifier(_settings(telegram_notify_bot_token="123:abc", telegram_notify_chat_id="42"))

    # Must not raise — a failed notification is not a reason to break the
    # rest of the message-bus publish (core/message_bus.py already isolates
    # handler errors, but this shouldn't need to rely on that safety net).
    await notifier.handle_reminder(ReminderDue(event_id=1, title="x", event_time=datetime.now()))
