from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from core.config import DATA_DIR

STATE_DB_PATH: Path = DATA_DIR / "ai_bridge" / "state.db"


class StateStore:
    """Tiny local key-value store (SQLite) for provider_manager's persisted
    state: the active provider and the last daily-reset date. Deliberately
    minimal — this isn't a general-purpose settings store."""

    def __init__(self, db_path: Path = STATE_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def get(self, key: str) -> str | None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
                    return row[0] if row else None
            finally:
                conn.close()

    def set(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO state (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
            finally:
                conn.close()
