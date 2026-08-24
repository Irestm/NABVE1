from __future__ import annotations

from modules.telegram_userbot import client_manager, login
from modules.telegram_userbot.domain import TelegramAccount


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.connected = False
        self.disconnected = False
        self.authorized = True
        self.sent_messages: list[tuple[str, str]] = []
        self.handlers: list[tuple[object, object]] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    def add_event_handler(self, callback, event) -> None:
        self.handlers.append((callback, event))

    async def send_message(self, recipient: str, text: str) -> None:
        self.sent_messages.append((recipient, text))


def _reset(monkeypatch) -> None:
    monkeypatch.setattr(client_manager, "_clients", {})


async def test_connect_account_fails_without_app_credentials(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: None)
    monkeypatch.setattr(client_manager, "get_secret", lambda name: "some-session")
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    connected = await client_manager.connect_account(account)

    assert connected is False
    assert client_manager.connected_account_ids() == []


async def test_connect_account_fails_without_a_stored_session(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: (123, "hash"))
    monkeypatch.setattr(client_manager, "get_secret", lambda name: None)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    connected = await client_manager.connect_account(account)

    assert connected is False


async def test_connect_account_succeeds_and_registers_a_handler(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: (123, "hash"))
    monkeypatch.setattr(client_manager, "get_secret", lambda name: "some-session")
    monkeypatch.setattr(client_manager, "TelegramClient", _FakeClient)
    monkeypatch.setattr(client_manager, "StringSession", lambda value=None: value)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    connected = await client_manager.connect_account(account)

    assert connected is True
    assert client_manager.connected_account_ids() == [1]
    fake_client = client_manager._clients[1]
    assert len(fake_client.handlers) == 1


async def test_connect_account_fails_when_session_is_unauthorized(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: (123, "hash"))
    monkeypatch.setattr(client_manager, "get_secret", lambda name: "some-session")

    class _UnauthorizedClient(_FakeClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.authorized = False

    monkeypatch.setattr(client_manager, "StringSession", lambda value=None: value)
    monkeypatch.setattr(client_manager, "TelegramClient", _UnauthorizedClient)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    connected = await client_manager.connect_account(account)

    assert connected is False
    assert client_manager.connected_account_ids() == []


async def test_connect_account_is_idempotent(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: (123, "hash"))
    monkeypatch.setattr(client_manager, "get_secret", lambda name: "some-session")
    monkeypatch.setattr(client_manager, "TelegramClient", _FakeClient)
    monkeypatch.setattr(client_manager, "StringSession", lambda value=None: value)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    await client_manager.connect_account(account)
    first_client = client_manager._clients[1]
    await client_manager.connect_account(account)

    assert client_manager._clients[1] is first_client


async def test_disconnect_account_removes_and_disconnects(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(login, "get_app_credentials", lambda: (123, "hash"))
    monkeypatch.setattr(client_manager, "get_secret", lambda name: "some-session")
    monkeypatch.setattr(client_manager, "TelegramClient", _FakeClient)
    monkeypatch.setattr(client_manager, "StringSession", lambda value=None: value)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")
    await client_manager.connect_account(account)
    fake_client = client_manager._clients[1]

    await client_manager.disconnect_account(1)

    assert client_manager.connected_account_ids() == []
    assert fake_client.disconnected is True


async def test_send_message_returns_false_when_not_connected(monkeypatch) -> None:
    _reset(monkeypatch)

    sent = await client_manager.send_message(999, "someone", "hi")

    assert sent is False


async def test_send_message_delegates_to_the_client(monkeypatch) -> None:
    _reset(monkeypatch)
    fake_client = _FakeClient()
    client_manager._clients[1] = fake_client

    sent = await client_manager.send_message(1, "someone", "hi")

    assert sent is True
    assert fake_client.sent_messages == [("someone", "hi")]


class _FakeSender:
    def __init__(self, *, bot=False, username=None, user_id=1, first_name=None, last_name=None) -> None:
        self.bot = bot
        self.username = username
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name


class _FakeEvent:
    def __init__(self, sender, raw_text: str) -> None:
        self._sender = sender
        self.raw_text = raw_text

    async def get_sender(self):
        return self._sender


async def test_forward_incoming_ignores_bots(monkeypatch) -> None:
    recorded = []
    monkeypatch.setattr(
        client_manager.messaging_service_layer,
        "record_incoming_message",
        lambda *args, **kwargs: recorded.append(args) or None,
    )
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")
    event = _FakeEvent(_FakeSender(bot=True, username="somebot"), "hi")

    await client_manager._forward_incoming(account, event)

    assert recorded == []


async def test_forward_incoming_uses_username_when_available(monkeypatch) -> None:
    captured = {}

    def fake_record(uow, source, identifier, label, text):
        captured["source"] = source
        captured["identifier"] = identifier
        captured["label"] = label
        captured["text"] = text
        return None

    monkeypatch.setattr(client_manager.messaging_service_layer, "record_incoming_message", fake_record)
    account = TelegramAccount(id=1, label="Рабочий", phone_number="+1000")
    event = _FakeEvent(_FakeSender(username="ira", first_name="Ира", last_name="К"), "привет")

    await client_manager._forward_incoming(account, event)

    assert captured["source"] == client_manager.SOURCE
    assert captured["identifier"] == "ira"
    assert captured["label"] == "Ира К (Рабочий)"
    assert captured["text"] == "привет"


async def test_forward_incoming_falls_back_to_user_id_without_a_username(monkeypatch) -> None:
    captured = {}

    def fake_record(uow, source, identifier, label, text):
        captured["identifier"] = identifier
        return None

    monkeypatch.setattr(client_manager.messaging_service_layer, "record_incoming_message", fake_record)
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")
    event = _FakeEvent(_FakeSender(username=None, user_id=555), "hi")

    await client_manager._forward_incoming(account, event)

    assert captured["identifier"] == "555"
