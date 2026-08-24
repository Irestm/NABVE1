from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.secret_store import SecretStoreUnavailableError
from modules.telegram_userbot import login as telegram_login
from modules.telegram_userbot import service_layer as telegram_service_layer
from modules.telegram_userbot.domain import TelegramAccount

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _no_stored_credentials(monkeypatch):
    monkeypatch.setattr(telegram_login, "get_app_credentials", lambda: None)


def test_get_credentials_status_reports_not_configured() -> None:
    response = client.get("/api/telegram/credentials", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_save_credentials_reports_configured(monkeypatch) -> None:
    monkeypatch.setattr(telegram_login, "store_app_credentials", lambda api_id, api_hash: None)

    response = client.post(
        "/api/telegram/credentials", json={"api_id": 12345, "api_hash": "abc"}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["configured"] is True


def test_save_credentials_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(api_id: int, api_hash: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(telegram_login, "store_app_credentials", _raise)

    response = client.post(
        "/api/telegram/credentials", json={"api_id": 12345, "api_hash": "abc"}, headers=AUTH
    )

    assert response.status_code == 500


def test_list_accounts_empty_by_default(monkeypatch) -> None:
    monkeypatch.setattr(telegram_service_layer, "list_accounts", lambda: [])

    response = client.get("/api/telegram/accounts", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_list_accounts_returns_connected_status(monkeypatch) -> None:
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")
    monkeypatch.setattr(telegram_service_layer, "list_accounts", lambda: [account])
    monkeypatch.setattr(telegram_service_layer, "is_account_connected", lambda account_id: True)

    response = client.get("/api/telegram/accounts", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body == [{"id": 1, "label": "Личный", "phone_number": "+1000", "connected": True}]


def test_delete_account_404s_when_not_found(monkeypatch) -> None:
    async def fake_remove(account_id: int) -> bool:
        return False

    monkeypatch.setattr(telegram_service_layer, "remove_account", fake_remove)

    response = client.delete("/api/telegram/accounts/999", headers=AUTH)

    assert response.status_code == 404


def test_start_login_returns_400_on_limit_error(monkeypatch) -> None:
    async def fake_start(label: str, phone_number: str) -> str:
        raise telegram_service_layer.TelegramAccountLimitError("too many")

    monkeypatch.setattr(telegram_service_layer, "start_account_login", fake_start)

    response = client.post(
        "/api/telegram/accounts/login/start",
        json={"label": "Личный", "phone_number": "+1000"},
        headers=AUTH,
    )

    assert response.status_code == 400


def test_start_login_returns_a_token(monkeypatch) -> None:
    async def fake_start(label: str, phone_number: str) -> str:
        return "fake-token"

    monkeypatch.setattr(telegram_service_layer, "start_account_login", fake_start)

    response = client.post(
        "/api/telegram/accounts/login/start",
        json={"label": "Личный", "phone_number": "+1000"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json() == {"token": "fake-token"}


def test_submit_code_reports_needs_password(monkeypatch) -> None:
    async def fake_submit(token: str, code: str):
        return True, None

    monkeypatch.setattr(telegram_service_layer, "submit_login_code", fake_submit)

    response = client.post(
        "/api/telegram/accounts/login/code", json={"token": "tok", "code": "12345"}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {"needs_password": True, "account": None}


def test_submit_code_returns_the_account_when_done(monkeypatch) -> None:
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    async def fake_submit(token: str, code: str):
        return False, account

    monkeypatch.setattr(telegram_service_layer, "submit_login_code", fake_submit)
    monkeypatch.setattr(telegram_service_layer, "is_account_connected", lambda account_id: True)

    response = client.post(
        "/api/telegram/accounts/login/code", json={"token": "tok", "code": "12345"}, headers=AUTH
    )

    assert response.status_code == 200
    body = response.json()
    assert body["needs_password"] is False
    assert body["account"]["label"] == "Личный"


def test_submit_code_returns_400_on_login_error(monkeypatch) -> None:
    async def fake_submit(token: str, code: str):
        raise telegram_login.TelegramLoginError("bad code")

    monkeypatch.setattr(telegram_service_layer, "submit_login_code", fake_submit)

    response = client.post(
        "/api/telegram/accounts/login/code", json={"token": "tok", "code": "wrong"}, headers=AUTH
    )

    assert response.status_code == 400


def test_submit_password_returns_the_account(monkeypatch) -> None:
    account = TelegramAccount(id=1, label="Личный", phone_number="+1000")

    async def fake_submit(token: str, password: str):
        return account

    monkeypatch.setattr(telegram_service_layer, "submit_login_password", fake_submit)
    monkeypatch.setattr(telegram_service_layer, "is_account_connected", lambda account_id: True)

    response = client.post(
        "/api/telegram/accounts/login/password",
        json={"token": "tok", "password": "hunter2"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["label"] == "Личный"


def test_list_contacts_empty_by_default(monkeypatch) -> None:
    monkeypatch.setattr(telegram_service_layer, "list_watched_contacts", lambda: [])

    response = client.get("/api/telegram/contacts", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_add_contact_returns_400_on_limit_error(monkeypatch) -> None:
    def fake_add(identifier: str, note: str = "") -> int:
        raise telegram_service_layer.WatchedContactLimitError("too many")

    monkeypatch.setattr(telegram_service_layer, "add_watched_contact", fake_add)

    response = client.post("/api/telegram/contacts", json={"identifier": "ira"}, headers=AUTH)

    assert response.status_code == 400


def test_add_contact_returns_the_created_contact(monkeypatch) -> None:
    monkeypatch.setattr(telegram_service_layer, "add_watched_contact", lambda identifier, note="": 5)

    response = client.post("/api/telegram/contacts", json={"identifier": "ira", "note": "sister"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"id": 5, "identifier": "ira", "note": "sister"}


def test_delete_contact_404s_when_not_found(monkeypatch) -> None:
    monkeypatch.setattr(main_module.messaging_service_layer, "remove_watched_contact", lambda uow, cid: False)

    response = client.delete("/api/telegram/contacts/999", headers=AUTH)

    assert response.status_code == 404


def test_pending_messages_empty_by_default(monkeypatch) -> None:
    monkeypatch.setattr(main_module.messaging_service_layer, "list_pending", lambda uow: [])

    response = client.get("/api/messaging/pending", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_telegram_routes_without_auth_are_rejected() -> None:
    response = client.get("/api/telegram/accounts")

    assert response.status_code == 401
