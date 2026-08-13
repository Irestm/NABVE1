from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.meeting_recorder.repository import MeetingRecordingRepository


class MeetingRecordingUnitOfWork(SqliteUnitOfWork):
    recordings: MeetingRecordingRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "MeetingRecordingUnitOfWork":
        super().__enter__()
        self.recordings = MeetingRecordingRepository(self.connection)
        return self
