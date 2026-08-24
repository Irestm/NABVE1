from __future__ import annotations

import sqlite3
from datetime import date, datetime

from core.ports import AbstractRepository
from modules.fitness_tracker.domain import (
    BioProfileSnapshot,
    BodyMeasurement,
    Goal,
    GoalType,
    MealLogEntry,
    ProgressPhoto,
)

_BIO_TABLE = "fitness_bio_profile_history"
_MEASUREMENTS_TABLE = "fitness_body_measurements"
_GOALS_TABLE = "fitness_goals"
_MEALS_TABLE = "fitness_meals_log"
_PHOTOS_TABLE = "fitness_progress_photos"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_BIO_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sex TEXT,
            age INTEGER,
            height_cm REAL,
            weight_kg REAL,
            bmi REAL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MEASUREMENTS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body_part TEXT NOT NULL,
            value_cm REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_GOALS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_type TEXT NOT NULL,
            description TEXT NOT NULL,
            target_value REAL,
            unit TEXT,
            deadline TEXT,
            created_at TEXT NOT NULL,
            achieved_at TEXT
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MEALS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            estimated_calories REAL,
            protein_g REAL,
            fat_g REAL,
            carbs_g REAL,
            confidence TEXT NOT NULL,
            source TEXT NOT NULL,
            photo_path TEXT,
            logged_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_PHOTOS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            note TEXT,
            taken_at TEXT NOT NULL
        )
        """
    )


def _row_to_bio_snapshot(row: sqlite3.Row) -> BioProfileSnapshot:
    return BioProfileSnapshot(
        id=row["id"],
        sex=row["sex"],
        age=row["age"],
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        bmi=row["bmi"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class BioProfileHistoryRepository(AbstractRepository[BioProfileSnapshot, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: BioProfileSnapshot) -> int:
        updated_at = item.updated_at or datetime.now()
        item.updated_at = updated_at
        cursor = self._conn.execute(
            f"""INSERT INTO {_BIO_TABLE} (sex, age, height_cm, weight_kg, bmi, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (item.sex, item.age, item.height_cm, item.weight_kg, item.bmi, updated_at.isoformat()),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> BioProfileSnapshot | None:
        row = self._conn.execute(f"SELECT * FROM {_BIO_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_bio_snapshot(row) if row is not None else None

    def latest(self) -> BioProfileSnapshot | None:
        row = self._conn.execute(f"SELECT * FROM {_BIO_TABLE} ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()
        return _row_to_bio_snapshot(row) if row is not None else None

    def list_weight_history(self) -> list[BioProfileSnapshot]:
        rows = self._conn.execute(
            f"SELECT * FROM {_BIO_TABLE} WHERE weight_kg IS NOT NULL ORDER BY updated_at ASC"
        ).fetchall()
        return [_row_to_bio_snapshot(row) for row in rows]


def _row_to_measurement(row: sqlite3.Row) -> BodyMeasurement:
    return BodyMeasurement(
        id=row["id"],
        body_part=row["body_part"],
        value_cm=row["value_cm"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
    )


class BodyMeasurementRepository(AbstractRepository[BodyMeasurement, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: BodyMeasurement) -> int:
        recorded_at = item.recorded_at or datetime.now()
        item.recorded_at = recorded_at
        cursor = self._conn.execute(
            f"INSERT INTO {_MEASUREMENTS_TABLE} (body_part, value_cm, recorded_at) VALUES (?, ?, ?)",
            (item.body_part, item.value_cm, recorded_at.isoformat()),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> BodyMeasurement | None:
        row = self._conn.execute(f"SELECT * FROM {_MEASUREMENTS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_measurement(row) if row is not None else None

    def list_all(self, body_part: str | None = None) -> list[BodyMeasurement]:
        if body_part is None:
            rows = self._conn.execute(f"SELECT * FROM {_MEASUREMENTS_TABLE} ORDER BY recorded_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {_MEASUREMENTS_TABLE} WHERE body_part = ? ORDER BY recorded_at DESC",
                (body_part,),
            ).fetchall()
        return [_row_to_measurement(row) for row in rows]


def _row_to_goal(row: sqlite3.Row) -> Goal:
    deadline = date.fromisoformat(row["deadline"]) if row["deadline"] else None
    achieved_at = datetime.fromisoformat(row["achieved_at"]) if row["achieved_at"] else None
    return Goal(
        id=row["id"],
        goal_type=GoalType(row["goal_type"]),
        description=row["description"],
        target_value=row["target_value"],
        unit=row["unit"],
        deadline=deadline,
        created_at=datetime.fromisoformat(row["created_at"]),
        achieved_at=achieved_at,
    )


class GoalRepository(AbstractRepository[Goal, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: Goal) -> int:
        created_at = item.created_at or datetime.now()
        item.created_at = created_at
        cursor = self._conn.execute(
            f"""INSERT INTO {_GOALS_TABLE}
                (goal_type, description, target_value, unit, deadline, created_at, achieved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item.goal_type.value,
                item.description,
                item.target_value,
                item.unit,
                item.deadline.isoformat() if item.deadline else None,
                created_at.isoformat(),
                item.achieved_at.isoformat() if item.achieved_at else None,
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> Goal | None:
        row = self._conn.execute(f"SELECT * FROM {_GOALS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_goal(row) if row is not None else None

    def list_all(self) -> list[Goal]:
        rows = self._conn.execute(f"SELECT * FROM {_GOALS_TABLE} ORDER BY created_at DESC").fetchall()
        return [_row_to_goal(row) for row in rows]

    def mark_achieved(self, key: int, achieved_at: datetime) -> None:
        self._conn.execute(f"UPDATE {_GOALS_TABLE} SET achieved_at = ? WHERE id = ?", (achieved_at.isoformat(), key))

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_GOALS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0


def _row_to_meal(row: sqlite3.Row) -> MealLogEntry:
    return MealLogEntry(
        id=row["id"],
        description=row["description"],
        estimated_calories=row["estimated_calories"],
        protein_g=row["protein_g"],
        fat_g=row["fat_g"],
        carbs_g=row["carbs_g"],
        confidence=row["confidence"],
        source=row["source"],
        photo_path=row["photo_path"],
        logged_at=datetime.fromisoformat(row["logged_at"]),
    )


class MealLogRepository(AbstractRepository[MealLogEntry, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: MealLogEntry) -> int:
        logged_at = item.logged_at or datetime.now()
        item.logged_at = logged_at
        cursor = self._conn.execute(
            f"""INSERT INTO {_MEALS_TABLE}
                (description, estimated_calories, protein_g, fat_g, carbs_g, confidence, source, photo_path, logged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.description,
                item.estimated_calories,
                item.protein_g,
                item.fat_g,
                item.carbs_g,
                item.confidence,
                item.source,
                item.photo_path,
                logged_at.isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> MealLogEntry | None:
        row = self._conn.execute(f"SELECT * FROM {_MEALS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_meal(row) if row is not None else None

    def list_all(self, limit: int | None = None) -> list[MealLogEntry]:
        query = f"SELECT * FROM {_MEALS_TABLE} ORDER BY logged_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            rows = self._conn.execute(query, (limit,)).fetchall()
        else:
            rows = self._conn.execute(query).fetchall()
        return [_row_to_meal(row) for row in rows]

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_MEALS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0


def _row_to_photo(row: sqlite3.Row) -> ProgressPhoto:
    return ProgressPhoto(
        id=row["id"],
        file_path=row["file_path"],
        note=row["note"],
        taken_at=datetime.fromisoformat(row["taken_at"]),
    )


class ProgressPhotoRepository(AbstractRepository[ProgressPhoto, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_schema(connection)
        self._conn = connection

    def add(self, item: ProgressPhoto) -> int:
        taken_at = item.taken_at or datetime.now()
        item.taken_at = taken_at
        cursor = self._conn.execute(
            f"INSERT INTO {_PHOTOS_TABLE} (file_path, note, taken_at) VALUES (?, ?, ?)",
            (item.file_path, item.note, taken_at.isoformat()),
        )
        return int(cursor.lastrowid)

    def get(self, key: int) -> ProgressPhoto | None:
        row = self._conn.execute(f"SELECT * FROM {_PHOTOS_TABLE} WHERE id = ?", (key,)).fetchone()
        return _row_to_photo(row) if row is not None else None

    def list_all(self) -> list[ProgressPhoto]:
        rows = self._conn.execute(f"SELECT * FROM {_PHOTOS_TABLE} ORDER BY taken_at DESC").fetchall()
        return [_row_to_photo(row) for row in rows]

    def delete(self, key: int) -> bool:
        cursor = self._conn.execute(f"DELETE FROM {_PHOTOS_TABLE} WHERE id = ?", (key,))
        return cursor.rowcount > 0
