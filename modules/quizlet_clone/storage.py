from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.config import settings
from core.ports import AbstractRepository
from core.uow import SqliteUnitOfWork
from modules.quizlet_clone.models import GameAttempt, GameMode, SetSource, StudySet, Term

_SETS_TABLE = "quizlet_sets"
_TERMS_TABLE = "quizlet_terms"
_ATTEMPTS_TABLE = "quizlet_game_attempts"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_SETS_TABLE} (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            quizlet_set_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TERMS_TABLE} (
            id TEXT PRIMARY KEY,
            set_id TEXT NOT NULL REFERENCES {_SETS_TABLE}(id) ON DELETE CASCADE,
            term TEXT NOT NULL,
            definition TEXT NOT NULL,
            position INTEGER NOT NULL,
            times_seen INTEGER NOT NULL DEFAULT 0,
            times_correct INTEGER NOT NULL DEFAULT 0,
            times_wrong INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_TERMS_TABLE}_set_id ON {_TERMS_TABLE}(set_id)")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_ATTEMPTS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id TEXT NOT NULL REFERENCES {_SETS_TABLE}(id) ON DELETE CASCADE,
            mode TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            score INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_ATTEMPTS_TABLE}_set_id ON {_ATTEMPTS_TABLE}(set_id)")


def _row_to_set(row: sqlite3.Row) -> StudySet:
    return StudySet(
        id=row["id"],
        title=row["title"],
        source=SetSource(row["source"]),
        quizlet_set_id=row["quizlet_set_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_term(row: sqlite3.Row) -> Term:
    return Term(
        id=row["id"],
        set_id=row["set_id"],
        term=row["term"],
        definition=row["definition"],
        position=row["position"],
        times_seen=row["times_seen"],
        times_correct=row["times_correct"],
        times_wrong=row["times_wrong"],
    )


def _row_to_attempt(row: sqlite3.Row) -> GameAttempt:
    return GameAttempt(
        id=row["id"],
        set_id=row["set_id"],
        mode=GameMode(row["mode"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        score=row["score"],
        total=row["total"],
    )


class StudySetRepository(AbstractRepository[StudySet, str]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: StudySet) -> str:
        created_at = item.created_at or datetime.now()
        self._conn.execute(
            f"INSERT INTO {_SETS_TABLE} (id, title, source, quizlet_set_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (item.id, item.title, item.source.value, item.quizlet_set_id, created_at.isoformat()),
        )
        item.created_at = created_at
        return item.id

    def get(self, key: str) -> StudySet | None:
        row = self._conn.execute(f"SELECT * FROM {_SETS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_set(row) if row is not None else None

    def get_by_quizlet_id(self, quizlet_set_id: str) -> StudySet | None:
        row = self._conn.execute(
            f"SELECT * FROM {_SETS_TABLE} WHERE quizlet_set_id = ?", (quizlet_set_id,)
        ).fetchone()
        return _row_to_set(row) if row is not None else None

    def list_all(self) -> list[StudySet]:
        rows = self._conn.execute(f"SELECT * FROM {_SETS_TABLE} ORDER BY created_at DESC").fetchall()
        return [_row_to_set(row) for row in rows]

    def update_title(self, set_id: str, title: str) -> None:
        self._conn.execute(f"UPDATE {_SETS_TABLE} SET title = ? WHERE id = ?", (title, set_id))

    def delete(self, key: str) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_SETS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0


class TermRepository(AbstractRepository[Term, str]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: Term) -> str:
        self._conn.execute(
            f"""
            INSERT INTO {_TERMS_TABLE}
                (id, set_id, term, definition, position, times_seen, times_correct, times_wrong)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.set_id,
                item.term,
                item.definition,
                item.position,
                item.times_seen,
                item.times_correct,
                item.times_wrong,
            ),
        )
        return item.id

    def get(self, key: str) -> Term | None:
        row = self._conn.execute(f"SELECT * FROM {_TERMS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_term(row) if row is not None else None

    def list_by_set(self, set_id: str) -> list[Term]:
        rows = self._conn.execute(
            f"SELECT * FROM {_TERMS_TABLE} WHERE set_id = ? ORDER BY position ASC", (set_id,)
        ).fetchall()
        return [_row_to_term(row) for row in rows]

    def update_definition(self, term_id: str, term: str, definition: str) -> None:
        self._conn.execute(
            f"UPDATE {_TERMS_TABLE} SET term = ?, definition = ? WHERE id = ?", (term, definition, term_id)
        )

    def record_answer(self, term_id: str, *, correct: bool) -> None:
        column = "times_correct" if correct else "times_wrong"
        self._conn.execute(
            f"UPDATE {_TERMS_TABLE} SET times_seen = times_seen + 1, {column} = {column} + 1 WHERE id = ?",
            (term_id,),
        )

    def delete_by_set(self, set_id: str) -> None:
        self._conn.execute(f"DELETE FROM {_TERMS_TABLE} WHERE set_id = ?", (set_id,))

    def delete(self, key: str) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TERMS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0


class GameAttemptRepository(AbstractRepository[GameAttempt, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: GameAttempt) -> int:
        cursor = self._conn.execute(
            f"""
            INSERT INTO {_ATTEMPTS_TABLE} (set_id, mode, started_at, finished_at, score, total)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item.set_id,
                item.mode.value,
                item.started_at.isoformat(),
                item.finished_at.isoformat() if item.finished_at else None,
                item.score,
                item.total,
            ),
        )
        item.id = cursor.lastrowid
        return item.id

    def get(self, key: int) -> GameAttempt | None:
        row = self._conn.execute(f"SELECT * FROM {_ATTEMPTS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_attempt(row) if row is not None else None

    def finish(self, attempt_id: int, *, score: int, total: int, finished_at: datetime) -> None:
        self._conn.execute(
            f"UPDATE {_ATTEMPTS_TABLE} SET score = ?, total = ?, finished_at = ? WHERE id = ?",
            (score, total, finished_at.isoformat(), attempt_id),
        )

    def list_by_set(self, set_id: str) -> list[GameAttempt]:
        rows = self._conn.execute(
            f"SELECT * FROM {_ATTEMPTS_TABLE} WHERE set_id = ? ORDER BY started_at DESC", (set_id,)
        ).fetchall()
        return [_row_to_attempt(row) for row in rows]


class QuizletUnitOfWork(SqliteUnitOfWork):
    sets: StudySetRepository
    terms: TermRepository
    attempts: GameAttemptRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "QuizletUnitOfWork":
        super().__enter__()
        self.sets = StudySetRepository(self.connection)
        self.terms = TermRepository(self.connection)
        self.attempts = GameAttemptRepository(self.connection)
        return self
