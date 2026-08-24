from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.fitness_tracker.repository import (
    BioProfileHistoryRepository,
    BodyMeasurementRepository,
    GoalRepository,
    MealLogRepository,
    ProgressPhotoRepository,
)


class FitnessUnitOfWork(SqliteUnitOfWork):
    bio_history: BioProfileHistoryRepository
    measurements: BodyMeasurementRepository
    goals: GoalRepository
    meals: MealLogRepository
    photos: ProgressPhotoRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "FitnessUnitOfWork":
        super().__enter__()
        self.bio_history = BioProfileHistoryRepository(self.connection)
        self.measurements = BodyMeasurementRepository(self.connection)
        self.goals = GoalRepository(self.connection)
        self.meals = MealLogRepository(self.connection)
        self.photos = ProgressPhotoRepository(self.connection)
        return self
