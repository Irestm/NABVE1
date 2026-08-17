from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.custom_commands.domain import ActionType, CustomCommand

_TABLE = "custom_commands"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id TEXT PRIMARY KEY,
            trigger_phrase TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_command(row: sqlite3.Row) -> CustomCommand:
    return CustomCommand(
        id=row["id"],
        trigger_phrase=row["trigger_phrase"],
        action_type=ActionType(row["action_type"]),
        action_payload=json.loads(row["action_payload"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class CustomCommandRepository(AbstractRepository[CustomCommand, str]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: CustomCommand) -> str:
        created_at = item.created_at or datetime.now()
        self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (id, trigger_phrase, action_type, action_payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item.id, item.trigger_phrase, item.action_type.value, json.dumps(item.action_payload), created_at.isoformat()),
        )
        item.created_at = created_at
        return item.id

    def get(self, key: str) -> CustomCommand | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_command(row) if row is not None else None

    def list_all(self) -> list[CustomCommand]:
        rows = self._conn.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at ASC").fetchall()
        return [_row_to_command(row) for row in rows]

    def update(self, item: CustomCommand) -> None:
        self._conn.execute(
            f"""
            UPDATE {_TABLE} SET trigger_phrase = ?, action_type = ?, action_payload = ?
            WHERE id = ?
            """,
            (item.trigger_phrase, item.action_type.value, json.dumps(item.action_payload), item.id),
        )

    def delete(self, key: str) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
