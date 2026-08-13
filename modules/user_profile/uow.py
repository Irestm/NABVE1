from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.user_profile.repository import ProfileFactRepository


class ProfileUnitOfWork(SqliteUnitOfWork):
    facts: ProfileFactRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "ProfileUnitOfWork":
        super().__enter__()
        self.facts = ProfileFactRepository(self.connection)
        return self
