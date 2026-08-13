from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.gmail.repository import GmailSyncRepository


class GmailUnitOfWork(SqliteUnitOfWork):
    sync_state: GmailSyncRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "GmailUnitOfWork":
        super().__enter__()
        self.sync_state = GmailSyncRepository(self.connection)
        return self
