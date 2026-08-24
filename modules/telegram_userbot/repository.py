from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.telegram_userbot.domain import TelegramAccount

_TABLE = "telegram_userbot_accounts"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_account(row: sqlite3.Row) -> TelegramAccount:
    return TelegramAccount(
        id=row["id"],
        label=row["label"],
        phone_number=row["phone_number"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class TelegramAccountRepository(AbstractRepository[TelegramAccount, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: TelegramAccount) -> int:
        created_at = item.created_at or datetime.now()
        item.created_at = created_at
        cursor = self._conn.execute(
            f"INSERT INTO {_TABLE} (label, phone_number, created_at) VALUES (?, ?, ?)",
            (item.label, item.phone_number, created_at.isoformat()),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> TelegramAccount | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_account(row) if row is not None else None

    def list_all(self) -> list[TelegramAccount]:
        rows = self._conn.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at ASC").fetchall()
        return [_row_to_account(row) for row in rows]

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
