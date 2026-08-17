from __future__ import annotations

import keyring
import pytest
from cryptography.fernet import Fernet, InvalidToken

from modules.user_profile import crypto


def test_get_or_create_fernet_key_generates_and_stores_a_new_key_when_absent(monkeypatch) -> None:
    stored = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)
    monkeypatch.setattr(
        keyring, "set_password", lambda service, username, password: stored.__setitem__((service, username), password)
    )

    key = crypto.get_or_create_fernet_key()

    assert stored[("assistant-profile", "encryption-key")] == key.decode()
    Fernet(key)


def test_get_or_create_fernet_key_returns_existing_key_without_regenerating(monkeypatch) -> None:
    existing_key = Fernet.generate_key()
    monkeypatch.setattr(keyring, "get_password", lambda service, username: existing_key.decode())

    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("set_password should not be called when a key already exists")

    monkeypatch.setattr(keyring, "set_password", _fail_if_called)

    key = crypto.get_or_create_fernet_key()

    assert key == existing_key


def test_get_fernet_round_trips_encryption(monkeypatch) -> None:
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)
    monkeypatch.setattr(keyring, "set_password", lambda *a, **k: None)

    fernet = crypto.get_fernet()
    token = fernet.encrypt(b"secret value")

    assert fernet.decrypt(token) == b"secret value"


def test_wrong_key_fails_to_decrypt_another_keys_token(monkeypatch) -> None:
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)
    monkeypatch.setattr(keyring, "set_password", lambda *a, **k: None)

    fernet = crypto.get_fernet()
    token = fernet.encrypt(b"secret value")

    other_fernet = Fernet(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        other_fernet.decrypt(token)
