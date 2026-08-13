from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from modules.gmail import login


@pytest.mark.parametrize(
    "old_email,new_email,expected",
    [
        (None, "ira@example.com", False),
        ("ira@example.com", "ira@example.com", False),
        ("IRA@example.com", "ira@example.com", False),
        ("old@example.com", "new@example.com", True),
    ],
)
def test_needs_confirmation(old_email: str | None, new_email: str, expected: bool) -> None:
    assert login._needs_confirmation(old_email, new_email) is expected


class _FakeCreds:
    def __init__(self, email: str) -> None:
        self.email = email
        self.token = "tok"
        self.refresh_token = "refresh"
        self.token_uri = "https://oauth2.googleapis.com/token"
        self.client_id = "cid"
        self.client_secret = "csecret"


class _FakeProfile:
    def __init__(self, email: str) -> None:
        self._email = email

    def execute(self) -> dict[str, str]:
        return {"emailAddress": self._email}


class _FakeUsers:
    def __init__(self, email: str) -> None:
        self._email = email

    def getProfile(self, userId: str) -> _FakeProfile:
        return _FakeProfile(self._email)


class _FakeService:
    def __init__(self, email: str) -> None:
        self._email = email

    def users(self) -> _FakeUsers:
        return _FakeUsers(self._email)


def test_get_email_reads_profile_from_built_service(monkeypatch) -> None:
    monkeypatch.setattr(login, "build_service", lambda creds: _FakeService(creds.email))
    assert login._get_email(_FakeCreds("ira@example.com")) == "ira@example.com"


class _FakeKeyring:
    def __init__(self, stored: str | None) -> None:
        self.stored = stored
        self.set_calls: list[tuple[str, str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        return self.stored

    def set_password(self, service: str, username: str, value: str) -> None:
        self.set_calls.append((service, username, value))
        self.stored = value


class _FakeFlow:
    def __init__(self, creds: _FakeCreds) -> None:
        self._creds = creds

    def run_local_server(self, port: int) -> _FakeCreds:
        return self._creds


def _install_fake_oauthlib(monkeypatch, creds: _FakeCreds) -> None:
    module = types.ModuleType("google_auth_oauthlib.flow")

    class _FakeInstalledAppFlow:
        @staticmethod
        def from_client_config(client_config: dict[str, Any], scopes: list[str]) -> _FakeFlow:
            return _FakeFlow(creds)

    module.InstalledAppFlow = _FakeInstalledAppFlow  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", types.ModuleType("google_auth_oauthlib"))


def test_run_login_stores_credentials_when_none_existed(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_SECRET", "csecret")

    creds = _FakeCreds("ira@example.com")
    _install_fake_oauthlib(monkeypatch, creds)

    fake_keyring = _FakeKeyring(stored=None)
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(login, "build_service", lambda c: _FakeService(c.email))

    login._run_login()

    assert len(fake_keyring.set_calls) == 1
    service, username, blob = fake_keyring.set_calls[0]
    assert service == login.KEYRING_SERVICE
    assert username == login.KEYRING_USERNAME
    assert json.loads(blob)["refresh_token"] == "refresh"


def test_run_login_prompts_and_overwrites_on_confirmed_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_SECRET", "csecret")

    old_blob = json.dumps(
        {
            "token": "old-tok",
            "refresh_token": "old-refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid",
            "client_secret": "csecret",
        }
    )
    fake_keyring = _FakeKeyring(stored=old_blob)
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    new_creds = _FakeCreds("new@example.com")
    _install_fake_oauthlib(monkeypatch, new_creds)

    monkeypatch.setattr(login, "_inspect_existing_account", lambda data: "old@example.com")
    monkeypatch.setattr(login, "build_service", lambda c: _FakeService(c.email))

    prompted: dict[str, Any] = {}

    def fake_confirm(source_label, old_identity, new_identity):
        prompted["called"] = (source_label, old_identity, new_identity)
        return True

    monkeypatch.setattr(login, "confirm_identity_mismatch", fake_confirm)

    login._run_login()

    assert prompted["called"][0] == "Gmail"
    assert len(fake_keyring.set_calls) == 1


def test_run_login_does_not_overwrite_on_declined_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_SECRET", "csecret")

    fake_keyring = _FakeKeyring(stored="{}")
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    new_creds = _FakeCreds("new@example.com")
    _install_fake_oauthlib(monkeypatch, new_creds)

    monkeypatch.setattr(login, "_inspect_existing_account", lambda data: "old@example.com")
    monkeypatch.setattr(login, "build_service", lambda c: _FakeService(c.email))
    monkeypatch.setattr(login, "confirm_identity_mismatch", lambda *a, **k: False)

    login._run_login()

    assert fake_keyring.set_calls == []


def test_run_login_fails_cleanly_without_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("ASSISTANT_GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("ASSISTANT_GMAIL_CLIENT_SECRET", raising=False)

    _install_fake_oauthlib(monkeypatch, _FakeCreds("x@example.com"))
    monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring(stored=None))

    with pytest.raises(SystemExit) as exc_info:
        login._run_login()

    assert exc_info.value.code == 1
