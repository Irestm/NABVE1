from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.delayed_execution.repository import DelayedCommandRepository


class DelayedExecutionUnitOfWork(SqliteUnitOfWork):
    commands: DelayedCommandRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "DelayedExecutionUnitOfWork":
        super().__enter__()
        self.commands = DelayedCommandRepository(self.connection)
        return self
