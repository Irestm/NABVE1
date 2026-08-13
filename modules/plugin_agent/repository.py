from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.plugin_agent.domain import GapCandidate, GapCandidateStatus

_TABLE_CANDIDATES = "plugin_gap_candidates"
_TABLE_EVENTS = "plugin_gap_events"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE_CANDIDATES} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            representative_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'collecting',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            generated_plugin_name TEXT,
            generated_plugin_path TEXT,
            safety_flags TEXT,
            error TEXT
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE_EVENTS} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL REFERENCES {_TABLE_CANDIDATES}(id),
            raw_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_candidate(row: sqlite3.Row) -> GapCandidate:
    return GapCandidate(
        id=row["id"],
        representative_text=row["representative_text"],
        status=GapCandidateStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        generated_plugin_name=row["generated_plugin_name"],
        generated_plugin_path=row["generated_plugin_path"],
        safety_flags=json.loads(row["safety_flags"]) if row["safety_flags"] else [],
        error=row["error"],
    )


class GapCandidateRepository(AbstractRepository[GapCandidate, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: GapCandidate) -> int:
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_TABLE_CANDIDATES}
                (representative_text, status, created_at, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (
                item.representative_text,
                item.status.value,
                (item.created_at or datetime.now()).isoformat(),
                (item.last_seen or datetime.now()).isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> GapCandidate | None:
        row = self._conn.execute(
            f"SELECT * FROM {_TABLE_CANDIDATES} WHERE id = ?", (key,)
        ).fetchone()
        return _row_to_candidate(row) if row is not None else None

    def list_open(self) -> list[GapCandidate]:
        placeholders = ",".join("?" for _ in ("collecting", "ready_for_generation", "requires_review"))
        rows = self._conn.execute(
            f"SELECT * FROM {_TABLE_CANDIDATES} WHERE status IN ({placeholders})",
            ("collecting", "ready_for_generation", "requires_review"),
        ).fetchall()
        return [_row_to_candidate(row) for row in rows]

    def list_by_status(self, status: GapCandidateStatus | None = None) -> list[GapCandidate]:
        if status is None:
            rows = self._conn.execute(
                f"SELECT * FROM {_TABLE_CANDIDATES} ORDER BY last_seen DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {_TABLE_CANDIDATES} WHERE status = ? ORDER BY last_seen DESC",
                (status.value,),
            ).fetchall()
        return [_row_to_candidate(row) for row in rows]

    def update(self, candidate: GapCandidate) -> None:
        assert candidate.id is not None
        self._conn.execute(
            f"""
            UPDATE {_TABLE_CANDIDATES} SET
                status = ?, last_seen = ?, generated_plugin_name = ?,
                generated_plugin_path = ?, safety_flags = ?, error = ?
            WHERE id = ?
            """,
            (
                candidate.status.value,
                (candidate.last_seen or datetime.now()).isoformat(),
                candidate.generated_plugin_name,
                candidate.generated_plugin_path,
                json.dumps(candidate.safety_flags, ensure_ascii=False) if candidate.safety_flags else None,
                candidate.error,
                candidate.id,
            ),
        )

    def record_event(self, candidate_id: int, raw_text: str, created_at: datetime) -> None:
        self._conn.execute(
            f"INSERT INTO {_TABLE_EVENTS} (candidate_id, raw_text, created_at) VALUES (?, ?, ?)",
            (candidate_id, raw_text, created_at.isoformat()),
        )

    def count_recent_events(self, candidate_id: int, cutoff: datetime) -> int:
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM {_TABLE_EVENTS} WHERE candidate_id = ? AND created_at >= ?",
            (candidate_id, cutoff.isoformat()),
        ).fetchone()
        return int(row[0])
