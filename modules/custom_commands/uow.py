from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.custom_commands.repository import CustomCommandRepository


class CustomCommandsUnitOfWork(SqliteUnitOfWork):
    commands: CustomCommandRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "CustomCommandsUnitOfWork":
        super().__enter__()
        self.commands = CustomCommandRepository(self.connection)
        return self
