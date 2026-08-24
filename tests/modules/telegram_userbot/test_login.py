from __future__ import annotations

import pytest
from telethon.errors import SessionPasswordNeededError

from modules.telegram_userbot import login


class _FakeSentCode:
    phone_code_hash = "fake-hash"


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.connected = False
        self.disconnected = False
        self.signed_in_with_code: str | None = None
        self.signed_in_with_password: str | None = None
        self._raise_password_needed = False
        self._session_value = "fake-session-string"

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_code_request(self, phone_number: str) -> _FakeSentCode:
        return _FakeSentCode()

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if password is not None:
            self.signed_in_with_password = password
            return
        if self._raise_password_needed:
            raise SessionPasswordNeededError(request=None)
        self.signed_in_with_code = code

    @property
    def session(self):
        client = self

        class _Session:
            def save(self_inner) -> str:
                return client._session_value

        return _Session()


@pytest.fixture(autouse=True)
def _clear_pending(monkeypatch):
    monkeypatch.setattr(login, "_pending_logins", {})


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch):
    monkeypatch.setattr(login, "get_app_credentials", lambda: (12345, "fake-api-hash"))


async def test_start_login_requires_app_credentials(monkeypatch) -> None:
    monkeypatch.setattr(login, "get_app_credentials", lambda: None)

    with pytest.raises(login.TelegramLoginError):
        await login.start_login("Личный", "+1000")


async def test_start_login_returns_a_token(monkeypatch) -> None:
    monkeypatch.setattr(login, "TelegramClient", _FakeClient)

    token = await login.start_login("Личный", "+1000")

    assert token
    assert login.pending_login_info(token) == ("Личный", "+1000")


async def test_submit_code_completes_the_login(monkeypatch) -> None:
    monkeypatch.setattr(login, "TelegramClient", _FakeClient)
    token = await login.start_login("Личный", "+1000")

    done, session_string = await login.submit_code(token, "12345")

    assert done is True
    assert session_string == "fake-session-string"
    assert login.pending_login_info(token) is None


async def test_submit_code_reports_password_needed(monkeypatch) -> None:
    class _PasswordNeededClient(_FakeClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._raise_password_needed = True

    monkeypatch.setattr(login, "TelegramClient", _PasswordNeededClient)
    token = await login.start_login("Личный", "+1000")

    done, session_string = await login.submit_code(token, "12345")

    assert done is False
    assert session_string == ""
    # Still pending — 2FA password comes next, not cleaned up yet.
    assert login.pending_login_info(token) == ("Личный", "+1000")


async def test_submit_password_completes_the_login(monkeypatch) -> None:
    class _PasswordNeededClient(_FakeClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._raise_password_needed = True

    monkeypatch.setattr(login, "TelegramClient", _PasswordNeededClient)
    token = await login.start_login("Личный", "+1000")
    await login.submit_code(token, "12345")

    session_string = await login.submit_password(token, "hunter2")

    assert session_string == "fake-session-string"
    assert login.pending_login_info(token) is None


async def test_submit_code_with_unknown_token_raises() -> None:
    with pytest.raises(login.TelegramLoginError):
        await login.submit_code("unknown-token", "12345")
