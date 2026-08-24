from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.image_generation.repository import GeneratedImageRepository


class ImageGenerationUnitOfWork(SqliteUnitOfWork):
    images: GeneratedImageRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "ImageGenerationUnitOfWork":
        super().__enter__()
        self.images = GeneratedImageRepository(self.connection)
        return self
