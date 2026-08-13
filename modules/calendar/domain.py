from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CalendarEvent:
    title: str
    event_time: datetime
    remind_before_minutes: int = 0
    notified: bool = False
    id: int | None = None
    created_at: datetime | None = None

    def is_due(self, now: datetime) -> bool:
        if self.notified:
            return False
        remind_at = self.event_time - timedelta(minutes=self.remind_before_minutes)
        return now >= remind_at
