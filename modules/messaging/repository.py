from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.messaging.domain import PendingMessage, PendingMessageStatus, WatchedContact

_CONTACTS_TABLE = "messaging_watched_contacts"
_MESSAGES_TABLE = "messaging_pending_messages"

_ACTIVE_STATUSES = (PendingMessageStatus.PENDING.value, PendingMessageStatus.SNOOZED.value)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_CONTACTS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            identifier TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MESSAGES_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            sender_identifier TEXT NOT NULL,
            sender_label TEXT NOT NULL,
            text TEXT NOT NULL,
            received_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            snooze_until TEXT
        )
        """
    )


def _row_to_contact(row: sqlite3.Row) -> WatchedContact:
    return WatchedContact(
        id=row["id"],
        source=row["source"],
        identifier=row["identifier"],
        note=row["note"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_message(row: sqlite3.Row) -> PendingMessage:
    return PendingMessage(
        id=row["id"],
        source=row["source"],
        sender_identifier=row["sender_identifier"],
        sender_label=row["sender_label"],
        text=row["text"],
        received_at=datetime.fromisoformat(row["received_at"]),
        status=PendingMessageStatus(row["status"]),
        snooze_until=datetime.fromisoformat(row["snooze_until"]) if row["snooze_until"] else None,
    )


class WatchedContactRepository(AbstractRepository[WatchedContact, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: WatchedContact) -> int:
        created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            f"INSERT INTO {_CONTACTS_TABLE} (source, identifier, note, created_at) VALUES (?, ?, ?, ?)",
            (item.source, item.identifier, item.note, created_at.isoformat()),
        )
        item.created_at = created_at
        return int(cursor.lastrowid)

    def get(self, key: int) -> WatchedContact | None:
        row = self._conn.execute(f"SELECT * FROM {_CONTACTS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_contact(row) if row is not None else None

    def list_all(self) -> list[WatchedContact]:
        rows = self._conn.execute(f"SELECT * FROM {_CONTACTS_TABLE} ORDER BY created_at ASC").fetchall()
        return [_row_to_contact(row) for row in rows]

    def find(self, source: str, identifier: str) -> WatchedContact | None:
        row = self._conn.execute(
            f"SELECT * FROM {_CONTACTS_TABLE} WHERE source = ? AND identifier = ?", (source, identifier)
        ).fetchone()
        return _row_to_contact(row) if row is not None else None

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_CONTACTS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0


class PendingMessageRepository(AbstractRepository[PendingMessage, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: PendingMessage) -> int:
        received_at = item.received_at or datetime.now()
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_MESSAGES_TABLE}
                (source, sender_identifier, sender_label, text, received_at, status, snooze_until)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.source,
                item.sender_identifier,
                item.sender_label,
                item.text,
                received_at.isoformat(),
                item.status.value,
                item.snooze_until.isoformat() if item.snooze_until else None,
            ),
        )
        item.received_at = received_at
        return int(cursor.lastrowid)

    def get(self, key: int) -> PendingMessage | None:
        row = self._conn.execute(f"SELECT * FROM {_MESSAGES_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_message(row) if row is not None else None

    def find_active(self, source: str, sender_identifier: str) -> PendingMessage | None:
        """The existing PENDING or SNOOZED row for this contact, if any —
        used by service_layer.record_incoming_message to merge a new
        message into a still-unhandled row instead of creating a second
        one per contact."""
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        row = self._conn.execute(
            f"""
            SELECT * FROM {_MESSAGES_TABLE}
            WHERE source = ? AND sender_identifier = ? AND status IN ({placeholders})
            ORDER BY received_at DESC LIMIT 1
            """,
            (source, sender_identifier, *_ACTIVE_STATUSES),
        ).fetchone()
        return _row_to_message(row) if row is not None else None

    def list_pending(self) -> list[PendingMessage]:
        rows = self._conn.execute(
            f"SELECT * FROM {_MESSAGES_TABLE} WHERE status = ? ORDER BY received_at ASC",
            (PendingMessageStatus.PENDING.value,),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def list_due_snoozes(self, now: datetime) -> list[PendingMessage]:
        rows = self._conn.execute(
            f"SELECT * FROM {_MESSAGES_TABLE} WHERE status = ? AND snooze_until <= ?",
            (PendingMessageStatus.SNOOZED.value, now.isoformat()),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def update(self, item: PendingMessage) -> None:
        assert item.id is not None
        received_at = item.received_at or datetime.now()
        self._conn.execute(
            f"""
            UPDATE {_MESSAGES_TABLE} SET
                sender_label = ?, text = ?, received_at = ?, status = ?, snooze_until = ?
            WHERE id = ?
            """,
            (
                item.sender_label,
                item.text,
                received_at.isoformat(),
                item.status.value,
                item.snooze_until.isoformat() if item.snooze_until else None,
                item.id,
            ),
        )
