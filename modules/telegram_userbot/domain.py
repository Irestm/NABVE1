from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MAX_ACCOUNTS = 3


@dataclass
class TelegramAccount:
    label: str
    phone_number: str
    id: int | None = None
    created_at: datetime | None = None

    @property
    def session_secret_name(self) -> str:
        assert self.id is not None
        return f"telegram_userbot_session_{self.id}"
