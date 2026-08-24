from __future__ import annotations

import pytest

from modules.telegram_userbot import client_manager, login, service_layer
from modules.telegram_userbot.uow import TelegramUserbotUnitOfWork


def _uow_factory(tmp_path):
    def factory() -> TelegramUserbotUnitOfWork:
        return TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db")

    return factory


@pytest.fixture(autouse=True)
def _isolated_uow(monkeypatch, tmp_path):
    monkeypatch.setattr(service_layer, "TelegramUserbotUnitOfWork", _uow_factory(tmp_path))


@pytest.fixture(autouse=True)
def _fake_secret_store(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(service_layer, "store_secret", lambda name, value: store.__setitem__(name, value))
    monkeypatch.setattr(service_layer, "delete_secret", lambda name: store.pop(name, None))
    return store


@pytest.fixture(autouse=True)
def _no_op_client_manager(monkeypatch):
    connected: set[int] = set()

    async def fake_connect(account) -> bool:
        connected.add(account.id)
        return True

    async def fake_disconnect(account_id: int) -> None:
        connected.discard(account_id)

    monkeypatch.setattr(client_manager, "connect_account", fake_connect)
    monkeypatch.setattr(client_manager, "disconnect_account", fake_disconnect)
    monkeypatch.setattr(client_manager, "connected_account_ids", lambda: list(connected))
    return connected


def test_add_account_respects_the_limit(monkeypatch) -> None:
    for i in range(service_layer.MAX_ACCOUNTS):
        service_layer.add_account(f"acc{i}", f"+{i}")

    with pytest.raises(service_layer.TelegramAccountLimitError):
        service_layer.add_account("one-too-many", "+999")


async def test_start_account_login_respects_the_limit(monkeypatch) -> None:
    for i in range(service_layer.MAX_ACCOUNTS):
        service_layer.add_account(f"acc{i}", f"+{i}")

    with pytest.raises(service_layer.TelegramAccountLimitError):
        await service_layer.start_account_login("one-too-many", "+999")


async def test_submit_login_code_creates_the_account_when_done(monkeypatch, _fake_secret_store) -> None:
    monkeypatch.setattr(login, "pending_login_info", lambda token: ("Личный", "+1000"))

    async def fake_submit_code(token: str, code: str) -> tuple[bool, str]:
        return True, "fake-session-string"

    monkeypatch.setattr(login, "submit_code", fake_submit_code)

    needs_password, account = await service_layer.submit_login_code("tok", "12345")

    assert needs_password is False
    assert account is not None
    assert account.label == "Личный"
    assert _fake_secret_store[account.session_secret_name] == "fake-session-string"


async def test_submit_login_code_reports_needs_password(monkeypatch, _fake_secret_store) -> None:
    monkeypatch.setattr(login, "pending_login_info", lambda token: ("Личный", "+1000"))

    async def fake_submit_code(token: str, code: str) -> tuple[bool, str]:
        return False, ""

    monkeypatch.setattr(login, "submit_code", fake_submit_code)

    needs_password, account = await service_layer.submit_login_code("tok", "12345")

    assert needs_password is True
    assert account is None
    assert len(service_layer.list_accounts()) == 0


async def test_submit_login_password_creates_the_account(monkeypatch, _fake_secret_store) -> None:
    monkeypatch.setattr(login, "pending_login_info", lambda token: ("Личный", "+1000"))

    async def fake_submit_password(token: str, password: str) -> str:
        return "fake-session-string"

    monkeypatch.setattr(login, "submit_password", fake_submit_password)

    account = await service_layer.submit_login_password("tok", "hunter2")

    assert account.label == "Личный"
    assert account.phone_number == "+1000"


async def test_remove_account_disconnects_and_deletes(monkeypatch, _fake_secret_store, _no_op_client_manager) -> None:
    account = service_layer.add_account("Личный", "+1000")
    _fake_secret_store[account.session_secret_name] = "some-session"
    _no_op_client_manager.add(account.id)

    removed = await service_layer.remove_account(account.id)

    assert removed is True
    assert account.id not in _no_op_client_manager
    assert account.session_secret_name not in _fake_secret_store
    assert service_layer.list_accounts() == []


def test_watched_contacts_respect_the_limit(monkeypatch, tmp_path) -> None:
    from modules.messaging.uow import MessagingUnitOfWork

    def messaging_uow_factory() -> MessagingUnitOfWork:
        return MessagingUnitOfWork(db_path=tmp_path / "messaging.db")

    monkeypatch.setattr(service_layer, "MessagingUnitOfWork", messaging_uow_factory)

    for i in range(service_layer.MAX_WATCHED_CONTACTS):
        service_layer.add_watched_contact(f"contact{i}")

    with pytest.raises(service_layer.WatchedContactLimitError):
        service_layer.add_watched_contact("one-too-many")

    assert len(service_layer.list_watched_contacts()) == service_layer.MAX_WATCHED_CONTACTS
