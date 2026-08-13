from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.calendar.domain import CalendarEvent

_TABLE = "calendar_events"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_time TEXT NOT NULL,
            remind_before_minutes INTEGER NOT NULL DEFAULT 0,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=row["id"],
        title=row["title"],
        event_time=datetime.fromisoformat(row["event_time"]),
        remind_before_minutes=row["remind_before_minutes"],
        notified=bool(row["notified"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class CalendarEventRepository(AbstractRepository[CalendarEvent, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: CalendarEvent) -> int:
        created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (title, event_time, remind_before_minutes, notified, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item.title,
                item.event_time.isoformat(),
                item.remind_before_minutes,
                int(item.notified),
                created_at.isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> CalendarEvent | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_event(row) if row is not None else None

    def list_upcoming(self, now: datetime, limit: int = 20) -> list[CalendarEvent]:
        rows = self._conn.execute(
            f"""
            SELECT * FROM {_TABLE}
            WHERE event_time >= ?
            ORDER BY event_time ASC
            LIMIT ?
            """,
            (now.isoformat(), limit),
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_not_notified(self) -> list[CalendarEvent]:
        # Domain-level `CalendarEvent.is_due(now)` decides actual due-ness so
        # the reminder-window arithmetic lives in one place (testable
        # without a database) instead of duplicated in SQL.
        rows = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE notified = 0").fetchall()
        return [_row_to_event(row) for row in rows]

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0

    def mark_notified(self, key: int) -> None:
        self._conn.execute(f"UPDATE {_TABLE} SET notified = 1 WHERE id = ?", (key,))
