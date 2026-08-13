from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.calendar.repository import CalendarEventRepository


class CalendarUnitOfWork(SqliteUnitOfWork):
    events: CalendarEventRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "CalendarUnitOfWork":
        super().__enter__()
        self.events = CalendarEventRepository(self.connection)
        return self
