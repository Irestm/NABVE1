from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core.ports import AbstractRepository
from modules.user_profile.crypto import get_fernet
from modules.user_profile.domain import FactCategory, ProfileFact

_TABLE = "user_profile"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            key TEXT PRIMARY KEY,
            value_encrypted BLOB NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    # Additive migration: existing deployments only have the three columns
    # above (plain key-value store). New columns get a sensible default so
    # `profile_set`/`profile_get`/`profile_delete`/`profile_list_keys` keep
    # working unchanged on upgrade, and pre-existing rows are treated as
    # "core" facts (they were explicitly set, so they should never be
    # auto-evicted like episodic memory).
    existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({_TABLE})")}
    migrations = {
        "category": f"ALTER TABLE {_TABLE} ADD COLUMN category TEXT NOT NULL DEFAULT '{FactCategory.CORE.value}'",
        "importance": f"ALTER TABLE {_TABLE} ADD COLUMN importance REAL NOT NULL DEFAULT 1.0",
        "learned_at": f"ALTER TABLE {_TABLE} ADD COLUMN learned_at TEXT",
        "last_used_at": f"ALTER TABLE {_TABLE} ADD COLUMN last_used_at TEXT",
    }
    for column, ddl in migrations.items():
        if column not in existing_columns:
            conn.execute(ddl)
    # Backfill learned_at/last_used_at from the original updated_at for rows
    # written before this migration (both new columns are NULL for them).
    conn.execute(
        f"UPDATE {_TABLE} SET learned_at = updated_at WHERE learned_at IS NULL"
    )
    conn.execute(
        f"UPDATE {_TABLE} SET last_used_at = updated_at WHERE last_used_at IS NULL"
    )


def _row_to_fact(row: sqlite3.Row) -> ProfileFact:
    fernet = get_fernet()
    value = fernet.decrypt(row["value_encrypted"]).decode()
    return ProfileFact(
        key=row["key"],
        value=value,
        category=FactCategory(row["category"]),
        importance=row["importance"],
        learned_at=datetime.fromisoformat(row["learned_at"]),
        last_used_at=datetime.fromisoformat(row["last_used_at"]),
    )


class ProfileFactRepository(AbstractRepository[ProfileFact, str]):
    """Encrypted key-value fact store. Values are Fernet-encrypted at rest
    (see modules/user_profile/crypto.py); key, category, importance and
    timestamps stay in the clear since they're needed for querying/eviction
    and reveal nothing about the fact's content."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: ProfileFact) -> str:
        encrypted = get_fernet().encrypt(item.value.encode())
        self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (key, value_encrypted, updated_at, category, importance, learned_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_encrypted = excluded.value_encrypted,
                updated_at = excluded.updated_at,
                category = excluded.category,
                importance = excluded.importance,
                last_used_at = excluded.last_used_at
            """,
            (
                item.key,
                encrypted,
                item.last_used_at.isoformat(),
                item.category.value,
                item.importance,
                item.learned_at.isoformat(),
                item.last_used_at.isoformat(),
            ),
        )
        return item.key

    def get(self, key: str) -> ProfileFact | None:
        row = self._conn.execute(
            f"SELECT * FROM {_TABLE} WHERE key = ?", (key,)
        ).fetchone()
        return _row_to_fact(row) if row is not None else None

    def delete(self, key: str) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE key = ?", (key,))
        return cursor.rowcount > 0

    def list_keys(self) -> list[str]:
        rows = self._conn.execute(f"SELECT key FROM {_TABLE} ORDER BY key").fetchall()
        return [row["key"] for row in rows]

    def list_by_category(self, category: FactCategory) -> list[ProfileFact]:
        rows = self._conn.execute(
            f"SELECT * FROM {_TABLE} WHERE category = ? ORDER BY last_used_at DESC",
            (category.value,),
        ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def touch(self, key: str) -> None:
        self._conn.execute(
            f"UPDATE {_TABLE} SET last_used_at = ? WHERE key = ?",
            (datetime.now(timezone.utc).isoformat(), key),
        )
