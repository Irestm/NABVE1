from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.telegram_userbot.repository import TelegramAccountRepository


class TelegramUserbotUnitOfWork(SqliteUnitOfWork):
    accounts: TelegramAccountRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "TelegramUserbotUnitOfWork":
        super().__enter__()
        self.accounts = TelegramAccountRepository(self.connection)
        return self
