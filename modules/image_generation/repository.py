from __future__ import annotations

import sqlite3
from datetime import datetime

from core.ports import AbstractRepository
from modules.image_generation.domain import GeneratedImage

_TABLE = "generated_images"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dir_path TEXT NOT NULL,
            prompt TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _row_to_image(row: sqlite3.Row) -> GeneratedImage:
    return GeneratedImage(
        id=row["id"],
        dir_path=row["dir_path"],
        prompt=row["prompt"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class GeneratedImageRepository(AbstractRepository[GeneratedImage, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: GeneratedImage) -> int:
        created_at = item.created_at or datetime.now()
        item.created_at = created_at
        cursor = self._conn.execute(
            f"INSERT INTO {_TABLE} (dir_path, prompt, source, created_at) VALUES (?, ?, ?, ?)",
            (item.dir_path, item.prompt, item.source, created_at.isoformat()),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> GeneratedImage | None:
        row = self._conn.execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_image(row) if row is not None else None

    def list_all(self) -> list[GeneratedImage]:
        rows = self._conn.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at DESC").fetchall()
        return [_row_to_image(row) for row in rows]

    def update(self, item: GeneratedImage) -> None:
        assert item.id is not None
        self._conn.execute(
            f"UPDATE {_TABLE} SET dir_path = ?, prompt = ?, source = ? WHERE id = ?",
            (item.dir_path, item.prompt, item.source, item.id),
        )

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
