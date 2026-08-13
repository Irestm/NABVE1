from __future__ import annotations

import json
import sqlite3

_TABLE = "gmail_sync_state"
_SINGLETON_ID = 1


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY CHECK (id = {_SINGLETON_ID}),
            last_history_id TEXT
        )
        """
    )
    # Additive migration: existing deployments only have last_history_id.
    # processed_message_ids tracks which Gmail message ids from the CURRENT
    # (not-yet-cursor-advanced) history batch have already been turned into
    # a PendingMessage — see GmailPoller._check_once. Without it, a poll
    # tick that records message A successfully and then fails on message B
    # would re-fetch the same batch (last_history_id never advanced past
    # it) next tick and append A's text into its PendingMessage row a
    # second time, since record_incoming_message has no idea A was already
    # handled.
    existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({_TABLE})")}
    if "processed_message_ids" not in existing_columns:
        conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN processed_message_ids TEXT")


class GmailSyncRepository:
    """Not an AbstractRepository[T, K] — there's no keyed collection here,
    just one process-wide cursor value (Gmail History API's historyId), so
    a plain get/set pair fits better than the other modules' add/get-by-key
    shape. Kept in a normal sqlite table rather than keyring: keyring in
    this project is reserved for secrets (see modules.gmail.client's OAuth
    token blob), while a sync cursor is ordinary mutable app state, same
    convention as every other module's small relational state."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def get_last_history_id(self) -> str | None:
        row = self._conn.execute(
            f"SELECT last_history_id FROM {_TABLE} WHERE id = ?", (_SINGLETON_ID,)
        ).fetchone()
        return row["last_history_id"] if row is not None else None

    def set_last_history_id(self, value: str) -> None:
        self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (id, last_history_id) VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET last_history_id = excluded.last_history_id
            """,
            (_SINGLETON_ID, value),
        )

    def get_processed_message_ids(self) -> set[str]:
        """Gmail message ids from the batch covered by the CURRENT
        last_history_id that have already been recorded — cleared whenever
        the cursor itself advances (see set_last_history_id_and_clear_processed),
        since a past cursor position's message ids can never be returned
        again by the History API and so are pointless to keep remembering."""
        row = self._conn.execute(
            f"SELECT processed_message_ids FROM {_TABLE} WHERE id = ?", (_SINGLETON_ID,)
        ).fetchone()
        if row is None or not row["processed_message_ids"]:
            return set()
        return set(json.loads(row["processed_message_ids"]))

    def add_processed_message_id(self, message_id: str) -> None:
        current = self.get_processed_message_ids()
        current.add(message_id)
        self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (id, processed_message_ids) VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET processed_message_ids = excluded.processed_message_ids
            """,
            (_SINGLETON_ID, json.dumps(sorted(current))),
        )

    def set_last_history_id_and_clear_processed(self, value: str) -> None:
        self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (id, last_history_id, processed_message_ids) VALUES (?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET last_history_id = excluded.last_history_id,
                processed_message_ids = NULL
            """,
            (_SINGLETON_ID, value),
        )
