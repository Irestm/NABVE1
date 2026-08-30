from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.calendar.domain import CalendarEvent, RecurrenceRule

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
    # Additive migration — same "PRAGMA table_info, ALTER TABLE per missing
    # column" shape as modules/user_profile/repository.py's own migration.
    existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({_TABLE})")}
    migrations = {
        "color": f"ALTER TABLE {_TABLE} ADD COLUMN color TEXT",
        "category": f"ALTER TABLE {_TABLE} ADD COLUMN category TEXT",
        "recurrence": f"ALTER TABLE {_TABLE} ADD COLUMN recurrence TEXT NOT NULL DEFAULT '{RecurrenceRule.NONE.value}'",
        "critical": f"ALTER TABLE {_TABLE} ADD COLUMN critical INTEGER NOT NULL DEFAULT 0",
    }
    for column, ddl in migrations.items():
        if column not in existing_columns:
            conn.execute(ddl)


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=row["id"],
        title=row["title"],
        event_time=datetime.fromisoformat(row["event_time"]),
        remind_before_minutes=row["remind_before_minutes"],
        notified=bool(row["notified"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        color=row["color"],
        category=row["category"],
        recurrence=RecurrenceRule(row["recurrence"]),
        critical=bool(row["critical"]),
    )


class CalendarEventRepository(AbstractRepository[CalendarEvent, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: CalendarEvent) -> int:
        created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_TABLE}
                (title, event_time, remind_before_minutes, notified, created_at, color, category, recurrence, critical)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.title,
                item.event_time.isoformat(),
                item.remind_before_minutes,
                int(item.notified),
                created_at.isoformat(),
                item.color,
                item.category,
                item.recurrence.value,
                int(item.critical),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> CalendarEvent | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_event(row) if row is not None else None

    def list_upcoming(self, now: datetime, limit: int = 20) -> list[CalendarEvent]:
        # A recurring event's own stored event_time can be in the past (its
        # first-ever occurrence) while it still recurs into the future, so a
        # plain "event_time >= now" filter would hide it — pull every
        # recurring row regardless of its stored event_time too, project
        # each to its actual next occurrence in Python (CalendarEvent.
        # next_occurrence_on_or_after — the same recurrence arithmetic
        # check_due_reminders relies on), then sort/limit on that.
        rows = self._conn.execute(
            f"""
            SELECT * FROM {_TABLE}
            WHERE event_time >= ? OR recurrence != ?
            """,
            (now.isoformat(), RecurrenceRule.NONE.value),
        ).fetchall()
        events = [_row_to_event(row) for row in rows]
        projected = [(event.next_occurrence_on_or_after(now), event) for event in events]
        projected.sort(key=lambda pair: pair[0])
        return [event for _occurrence, event in projected[:limit]]

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

    def reschedule_recurrence(self, key: int, next_event_time: datetime) -> None:
        """Advances a recurring event to its next occurrence in place
        (same row keeps its id/title/color/category — a recurring event is
        one logical thing, not N separate rows) and clears `notified` so
        check_due_reminders fires again for that next occurrence instead of
        the event going silent after its first reminder."""
        self._conn.execute(
            f"UPDATE {_TABLE} SET event_time = ?, notified = 0 WHERE id = ?",
            (next_event_time.isoformat(), key),
        )
