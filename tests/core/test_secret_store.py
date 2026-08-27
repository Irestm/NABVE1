from __future__ import annotations

import sys
import types

import pytest

from core import secret_store


class _FakeItem:
    def __init__(self, label: str, attributes: dict[str, str], secret: str) -> None:
        self.label = label
        self.attributes = attributes
        self.secret = secret
        self.deleted = False

    def get_attributes(self) -> dict[str, str]:
        return self.attributes

    def get_secret(self) -> bytes:
        return self.secret.encode("utf-8")

    def delete(self) -> None:
        self.deleted = True


class _FakeCollection:
    def __init__(self, locked: bool = False) -> None:
        self.locked = locked
        self.unlocked = False
        self.items: list[_FakeItem] = []

    def is_locked(self) -> bool:
        return self.locked

    def unlock(self) -> None:
        self.unlocked = True
        self.locked = False

    def get_all_items(self) -> list[_FakeItem]:
        return [item for item in self.items if not item.deleted]

    def create_item(self, label: str, attributes: dict[str, str], secret: str) -> _FakeItem:
        item = _FakeItem(label, attributes, secret)
        self.items.append(item)
        return item


def _install_fake_secretstorage(monkeypatch, collection: _FakeCollection) -> None:
    fake_module = types.SimpleNamespace(
        dbus_init=lambda: object(),
        get_default_collection=lambda connection: collection,
    )
    monkeypatch.setitem(sys.modules, "secretstorage", fake_module)


def test_store_secret_creates_an_item_with_expected_attributes(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)

    secret_store.store_secret("youtube_api_key", "abc123")

    assert len(collection.get_all_items()) == 1
    item = collection.get_all_items()[0]
    assert item.get_attributes() == {"application": "nabve", "name": "youtube_api_key"}
    assert item.get_secret() == b"abc123"


def test_store_secret_replaces_an_existing_item_with_the_same_name(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)

    secret_store.store_secret("youtube_api_key", "old-value")
    secret_store.store_secret("youtube_api_key", "new-value")

    remaining = collection.get_all_items()
    assert len(remaining) == 1
    assert remaining[0].get_secret() == b"new-value"


def test_store_secret_unlocks_a_locked_collection(monkeypatch) -> None:
    collection = _FakeCollection(locked=True)
    _install_fake_secretstorage(monkeypatch, collection)

    secret_store.store_secret("youtube_api_key", "abc123")

    assert collection.unlocked is True


def test_get_secret_returns_the_stored_value(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)
    secret_store.store_secret("youtube_api_key", "abc123")

    assert secret_store.get_secret("youtube_api_key") == "abc123"


def test_get_secret_finds_an_item_that_carries_extra_attributes(monkeypatch) -> None:
    # Regression: real secretstorage/libsecret silently adds its own
    # 'xdg:schema' attribute to every item on creation, on top of whatever
    # attributes we pass to create_item - comparing get_attributes() by
    # exact dict equality against our own two-key attributes dict then NEVER
    # matches, so every secret this module ever stored could be created
    # successfully but never read back or overwritten (see
    # core.secret_store._matches's own docstring). This mimics that by
    # planting an item with one extra attribute key we never asked for.
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)
    collection.items.append(
        _FakeItem(
            "NABVE secret: youtube_api_key",
            {"application": "nabve", "name": "youtube_api_key", "xdg:schema": "org.freedesktop.Secret.Generic"},
            "abc123",
        )
    )

    assert secret_store.get_secret("youtube_api_key") == "abc123"


def test_store_secret_replaces_an_item_that_carries_extra_attributes(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)
    collection.items.append(
        _FakeItem(
            "NABVE secret: youtube_api_key",
            {"application": "nabve", "name": "youtube_api_key", "xdg:schema": "org.freedesktop.Secret.Generic"},
            "old-value",
        )
    )

    secret_store.store_secret("youtube_api_key", "new-value")

    remaining = collection.get_all_items()
    assert len(remaining) == 1
    assert remaining[0].get_secret() == b"new-value"


def test_get_secret_returns_none_when_no_item_matches(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)

    assert secret_store.get_secret("youtube_api_key") is None


def test_get_secret_returns_none_when_store_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "secretstorage", None)

    assert secret_store.get_secret("youtube_api_key") is None


def test_delete_secret_removes_the_matching_item(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)
    secret_store.store_secret("youtube_api_key", "abc123")

    secret_store.delete_secret("youtube_api_key")

    assert collection.get_all_items() == []


def test_delete_secret_leaves_other_names_untouched(monkeypatch) -> None:
    collection = _FakeCollection()
    _install_fake_secretstorage(monkeypatch, collection)
    secret_store.store_secret("youtube_api_key", "abc123")
    secret_store.store_secret("other_key", "xyz789")

    secret_store.delete_secret("youtube_api_key")

    remaining = collection.get_all_items()
    assert len(remaining) == 1
    assert remaining[0].get_attributes()["name"] == "other_key"


def test_store_secret_raises_when_secretstorage_not_installed(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "secretstorage", None)

    with pytest.raises(secret_store.SecretStoreUnavailableError):
        secret_store.store_secret("youtube_api_key", "abc123")


def test_delete_secret_raises_when_secretstorage_not_installed(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "secretstorage", None)

    with pytest.raises(secret_store.SecretStoreUnavailableError):
        secret_store.delete_secret("youtube_api_key")
