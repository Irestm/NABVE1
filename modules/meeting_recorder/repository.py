from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.meeting_recorder.domain import (
    Recording,
    RecordingStatus,
    SummaryStatus,
    TranscriptStatus,
)

_TABLE = "meeting_recordings"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dir_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'uploading',
            error TEXT,
            duration_seconds REAL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            mic_only INTEGER NOT NULL DEFAULT 0,
            context_label TEXT,
            transcript_status TEXT NOT NULL DEFAULT 'pending',
            transcript_progress REAL NOT NULL DEFAULT 0,
            transcript_error TEXT,
            summary_status TEXT NOT NULL DEFAULT 'pending',
            summary_error TEXT,
            delete_requested INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _row_to_recording(row: sqlite3.Row) -> Recording:
    return Recording(
        id=row["id"],
        dir_path=row["dir_path"],
        created_at=datetime.fromisoformat(row["created_at"]),
        status=RecordingStatus(row["status"]),
        error=row["error"],
        duration_seconds=row["duration_seconds"],
        size_bytes=row["size_bytes"],
        mic_only=bool(row["mic_only"]),
        context_label=row["context_label"],
        transcript_status=TranscriptStatus(row["transcript_status"]),
        transcript_progress=row["transcript_progress"],
        transcript_error=row["transcript_error"],
        summary_status=SummaryStatus(row["summary_status"]),
        summary_error=row["summary_error"],
        delete_requested=bool(row["delete_requested"]),
    )


class MeetingRecordingRepository(AbstractRepository[Recording, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: Recording) -> int:
        created_at = item.created_at or datetime.now()
        # Written back onto the passed-in object (unlike e.g.
        # modules.calendar's equivalent, which every caller there discards
        # right after add()) — modules.meeting_recorder.service_layer.
        # create_recording keeps and returns this exact object afterward, so
        # it must reflect what was actually persisted rather than staying
        # None until the next explicit get().
        item.created_at = created_at
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_TABLE} (
                dir_path, created_at, status, error, duration_seconds, size_bytes,
                mic_only, context_label, transcript_status, transcript_progress,
                transcript_error, summary_status, summary_error, delete_requested
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.dir_path,
                created_at.isoformat(),
                item.status.value,
                item.error,
                item.duration_seconds,
                item.size_bytes,
                int(item.mic_only),
                item.context_label,
                item.transcript_status.value,
                item.transcript_progress,
                item.transcript_error,
                item.summary_status.value,
                item.summary_error,
                int(item.delete_requested),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> Recording | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_recording(row) if row is not None else None

    def list_all(self) -> list[Recording]:
        rows = self._conn.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at DESC").fetchall()
        return [_row_to_recording(row) for row in rows]

    def list_by_status(self, status: RecordingStatus) -> list[Recording]:
        rows = self._conn.execute(
            f"SELECT * FROM {_TABLE} WHERE status = ? ORDER BY created_at ASC", (status.value,)
        ).fetchall()
        return [_row_to_recording(row) for row in rows]

    def list_ready_pending_transcript(self) -> list[Recording]:
        rows = self._conn.execute(
            f"""
            SELECT * FROM {_TABLE}
            WHERE status = ? AND transcript_status = ? AND delete_requested = 0
            ORDER BY created_at ASC
            """,
            (RecordingStatus.READY.value, TranscriptStatus.PENDING.value),
        ).fetchall()
        return [_row_to_recording(row) for row in rows]

    def list_pending_summary_only(self) -> list[Recording]:
        """Rows whose transcript is already DONE but whose summary is
        still PENDING — reached only via
        service_layer.recover_after_restart resetting a row that crashed
        mid-GENERATING back to PENDING. Without this separate query,
        transcribe_next's own claim query (transcript_status = PENDING)
        would never see such a row again, since its transcript_status is
        DONE, not PENDING — leaving the summary stuck forever."""
        rows = self._conn.execute(
            f"""
            SELECT * FROM {_TABLE}
            WHERE status = ? AND transcript_status = ? AND summary_status = ? AND delete_requested = 0
            ORDER BY created_at ASC
            """,
            (RecordingStatus.READY.value, TranscriptStatus.DONE.value, SummaryStatus.PENDING.value),
        ).fetchall()
        return [_row_to_recording(row) for row in rows]

    def update(self, item: Recording) -> None:
        assert item.id is not None
        self._conn.execute(
            f"""
            UPDATE {_TABLE} SET
                status = ?, error = ?, duration_seconds = ?, size_bytes = ?,
                mic_only = ?, context_label = ?, transcript_status = ?,
                transcript_progress = ?, transcript_error = ?, summary_status = ?,
                summary_error = ?, delete_requested = ?
            WHERE id = ?
            """,
            (
                item.status.value,
                item.error,
                item.duration_seconds,
                item.size_bytes,
                int(item.mic_only),
                item.context_label,
                item.transcript_status.value,
                item.transcript_progress,
                item.transcript_error,
                item.summary_status.value,
                item.summary_error,
                int(item.delete_requested),
                item.id,
            ),
        )

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
