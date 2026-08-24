from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Sex = Literal["male", "female"]
MealSource = Literal["photo", "text", "manual"]
Confidence = Literal["high", "medium", "low"]


class GoalType(str, enum.Enum):
    WEIGHT = "weight"
    STRENGTH = "strength"
    VOLUME = "volume"


@dataclass
class BioProfileSnapshot:
    """One row of fitness_bio_profile_history — the append-only log that is
    both "today's profile" (its most recent row) and the weight/BMI history
    chart's data source, so there is only one table to keep consistent
    instead of a separate current-state table plus a history table."""

    sex: Sex | None
    age: int | None
    height_cm: float | None
    weight_kg: float | None
    bmi: float | None
    id: int | None = None
    updated_at: datetime | None = None


@dataclass
class BodyMeasurement:
    body_part: str
    value_cm: float
    id: int | None = None
    recorded_at: datetime | None = None


@dataclass
class Goal:
    goal_type: GoalType
    description: str
    target_value: float | None = None
    unit: str | None = None
    deadline: date | None = None
    id: int | None = None
    created_at: datetime | None = None
    achieved_at: datetime | None = None


@dataclass
class MealLogEntry:
    description: str
    estimated_calories: float | None
    confidence: Confidence
    source: MealSource
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    photo_path: str | None = None
    id: int | None = None
    logged_at: datetime | None = None


@dataclass
class ProgressPhoto:
    file_path: str
    note: str | None = None
    id: int | None = None
    taken_at: datetime | None = None
