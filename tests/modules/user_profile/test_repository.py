from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import keyring
import pytest
from cryptography.fernet import Fernet

from modules.user_profile.domain import FactCategory, ProfileFact
from modules.user_profile.repository import ProfileFactRepository, ensure_schema
from modules.user_profile.uow import ProfileUnitOfWork


@pytest.fixture(autouse=True)
def _fake_keyring(monkeypatch):
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, username: stored.get((service, username)))
    monkeypatch.setattr(
        keyring, "set_password", lambda service, username, password: stored.__setitem__((service, username), password)
    )
    yield


def _uow(tmp_path) -> ProfileUnitOfWork:
    return ProfileUnitOfWork(tmp_path / "assistant.db")


def _fact(key: str, value: str, category: FactCategory = FactCategory.CORE) -> ProfileFact:
    now = datetime.now(timezone.utc)
    return ProfileFact(key=key, value=value, category=category, importance=1.0, learned_at=now, last_used_at=now)


def test_add_then_get_round_trips_the_plaintext_value(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.facts.add(_fact("stop_word", "стоп"))
        uow.commit()
        fact = uow.facts.get("stop_word")

    assert fact is not None
    assert fact.value == "стоп"
    assert fact.category is FactCategory.CORE


def test_value_is_encrypted_at_rest(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.facts.add(_fact("stop_word", "стоп"))
        uow.commit()

    conn = sqlite3.connect(tmp_path / "assistant.db")
    try:
        row = conn.execute("SELECT value_encrypted FROM user_profile WHERE key = ?", ("stop_word",)).fetchone()
    finally:
        conn.close()

    assert b"\xd1\x81\xd1\x82\xd0\xbe\xd0\xbf" not in row[0]  # UTF-8 for "стоп" must not appear in the ciphertext


def test_get_returns_none_for_unknown_key(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        assert uow.facts.get("does-not-exist") is None


def test_add_upserts_existing_key_but_preserves_learned_at(tmp_path) -> None:
    uow = _uow(tmp_path)
    original_learned_at = datetime.now(timezone.utc) - timedelta(days=5)
    with uow:
        first = _fact("wake_phrase", "привет")
        first.learned_at = original_learned_at
        uow.facts.add(first)
        uow.commit()

        second = _fact("wake_phrase", "здравствуй")
        uow.facts.add(second)
        uow.commit()
        stored = uow.facts.get("wake_phrase")

    assert stored is not None
    assert stored.value == "здравствуй"
    assert stored.learned_at == original_learned_at


def test_delete_removes_row_and_reports_whether_it_existed(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.facts.add(_fact("stop_word", "стоп"))
        uow.commit()
        removed = uow.facts.delete("stop_word")
        uow.commit()
        missing = uow.facts.delete("stop_word")

    assert removed is True
    assert missing is False


def test_list_keys_returns_sorted_keys(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.facts.add(_fact("wake_phrase", "привет"))
        uow.facts.add(_fact("stop_word", "стоп"))
        uow.commit()
        keys = uow.facts.list_keys()

    assert keys == sorted(keys)
    assert set(keys) == {"stop_word", "wake_phrase"}


def test_list_by_category_filters(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.facts.add(_fact("core_fact", "x", category=FactCategory.CORE))
        uow.facts.add(_fact("episodic_fact", "y", category=FactCategory.EPISODIC))
        uow.commit()
        episodic = uow.facts.list_by_category(FactCategory.EPISODIC)

    assert [f.key for f in episodic] == ["episodic_fact"]


def test_touch_updates_last_used_at(tmp_path) -> None:
    uow = _uow(tmp_path)
    old_time = datetime.now(timezone.utc) - timedelta(days=1)
    with uow:
        fact = _fact("wake_phrase", "привет")
        fact.last_used_at = old_time
        uow.facts.add(fact)
        uow.commit()
        uow.facts.touch("wake_phrase")
        uow.commit()
        updated = uow.facts.get("wake_phrase")

    assert updated is not None
    assert updated.last_used_at > old_time


def test_ensure_schema_migrates_a_pre_migration_table(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE user_profile (key TEXT PRIMARY KEY, value_encrypted BLOB NOT NULL, updated_at TEXT NOT NULL)"
        )
        fernet = Fernet(Fernet.generate_key())
        updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO user_profile (key, value_encrypted, updated_at) VALUES (?, ?, ?)",
            ("legacy_key", fernet.encrypt(b"legacy"), updated_at),
        )
        conn.commit()

        ensure_schema(conn)
        conn.commit()

        row = conn.execute("SELECT category, importance, learned_at, last_used_at FROM user_profile").fetchone()
    finally:
        conn.close()

    assert row[0] == FactCategory.CORE.value
    assert row[1] == 1.0
    assert row[2] == updated_at
    assert row[3] == updated_at
