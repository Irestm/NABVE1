from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.messaging.repository import (
    OutboundMessageRepository,
    PendingMessageRepository,
    WatchedContactRepository,
)


class MessagingUnitOfWork(SqliteUnitOfWork):
    contacts: WatchedContactRepository
    messages: PendingMessageRepository
    outbound: OutboundMessageRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "MessagingUnitOfWork":
        super().__enter__()
        self.contacts = WatchedContactRepository(self.connection)
        self.messages = PendingMessageRepository(self.connection)
        self.outbound = OutboundMessageRepository(self.connection)
        return self
