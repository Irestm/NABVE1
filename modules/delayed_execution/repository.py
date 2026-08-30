from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.delayed_execution.domain import DelayedCommand, DelayedCommandStatus

_TABLE = "delayed_commands"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_name TEXT NOT NULL,
            command_params TEXT NOT NULL,
            run_at TEXT NOT NULL,
            original_text TEXT NOT NULL,
            pre_confirmed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '{DelayedCommandStatus.PENDING.value}',
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_command(row: sqlite3.Row) -> DelayedCommand:
    return DelayedCommand(
        id=row["id"],
        command_name=row["command_name"],
        command_params=json.loads(row["command_params"]),
        run_at=datetime.fromisoformat(row["run_at"]),
        original_text=row["original_text"],
        pre_confirmed=bool(row["pre_confirmed"]),
        status=DelayedCommandStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class DelayedCommandRepository(AbstractRepository[DelayedCommand, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: DelayedCommand) -> int:
        created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_TABLE}
                (command_name, command_params, run_at, original_text, pre_confirmed, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.command_name,
                json.dumps(item.command_params, ensure_ascii=False),
                item.run_at.isoformat(),
                item.original_text,
                int(item.pre_confirmed),
                item.status.value,
                created_at.isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> DelayedCommand | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_command(row) if row is not None else None

    def list_pending(self) -> list[DelayedCommand]:
        rows = self._conn.execute(
            f"SELECT * FROM {_TABLE} WHERE status = ? ORDER BY run_at",
            (DelayedCommandStatus.PENDING.value,),
        ).fetchall()
        return [_row_to_command(row) for row in rows]

    def set_status(self, key: int, status: DelayedCommandStatus) -> bool:
        """Only advances a row that is still PENDING — a guard against two
        pollers (or a poll racing a manual cancel) acting on the same task."""
        cursor = self._conn.execute(
            f"UPDATE {_TABLE} SET status = ? WHERE id = ? AND status = ?",
            (status.value, key, DelayedCommandStatus.PENDING.value),
        )
        return cursor.rowcount > 0

    def force_status(self, key: int, status: DelayedCommandStatus) -> None:
        """Unconditional — used to mark a task FAILED after its dispatch
        raised, when the row was already moved off PENDING."""
        self._conn.execute(f"UPDATE {_TABLE} SET status = ? WHERE id = ?", (status.value, key))

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
