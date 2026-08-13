from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.message_bus import Event


@dataclass(frozen=True)
class ReminderDue(Event):
    """Published once per event when its reminder time is reached. Multiple
    subscribers can react independently — see
    modules/calendar/notification_adapter.py (desktop notification) and
    core/voice/announcements.py (spoken reminder, only while the voice loop
    is running)."""

    event_id: int
    title: str
    event_time: datetime
