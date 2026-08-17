from __future__ import annotations

import keyring
import keyring.errors

from modules.password_manager import manager


def test_store_password_calls_keyring_with_namespaced_service(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        keyring, "set_password", lambda service, username, password: calls.append((service, username, password))
    )

    manager.store_password("gmail", "me@example.com", "hunter2")

    assert calls == [("assistant-password:gmail", "me@example.com", "hunter2")]


def test_get_password_returns_stored_value(monkeypatch) -> None:
    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, username: "hunter2" if service == "assistant-password:gmail" else None,
    )

    assert manager.get_password("gmail", "me@example.com") == "hunter2"


def test_get_password_returns_none_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)

    assert manager.get_password("gmail", "me@example.com") is None


def test_delete_password_returns_true_on_success(monkeypatch) -> None:
    monkeypatch.setattr(keyring, "delete_password", lambda service, username: None)

    assert manager.delete_password("gmail", "me@example.com") is True


def test_delete_password_returns_false_when_not_found(monkeypatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise keyring.errors.PasswordDeleteError("not found")

    monkeypatch.setattr(keyring, "delete_password", _raise)

    assert manager.delete_password("gmail", "me@example.com") is False


def test_keyring_credential_store_adapter_delegates(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(keyring, "set_password", lambda service, username, password: calls.append(service))

    manager.KeyringCredentialStore.store_password("gmail", "me@example.com", "hunter2")

    assert calls == ["assistant-password:gmail"]
