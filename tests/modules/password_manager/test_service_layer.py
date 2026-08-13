from __future__ import annotations

import pytest

from modules.password_manager import service_layer
from modules.password_manager.domain import Credential


class FakeCredentialStore:
    def __init__(self) -> None:
        self._passwords: dict[tuple[str, str], str] = {}

    def store_password(self, service: str, username: str, password: str) -> None:
        self._passwords[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._passwords.get((service, username))

    def delete_password(self, service: str, username: str) -> bool:
        return self._passwords.pop((service, username), None) is not None


def test_store_and_get_roundtrip() -> None:
    store = FakeCredentialStore()
    service_layer.store(store, "github", "daniil", "hunter2")
    assert service_layer.get(store, "github", "daniil") == "hunter2"


def test_delete_returns_false_when_absent() -> None:
    store = FakeCredentialStore()
    assert service_layer.delete(store, "github", "daniil") is False


def test_credential_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        Credential(service="", username="daniil", password="x")
