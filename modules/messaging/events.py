from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.message_bus import Event


@dataclass(frozen=True)
class MessageReceived(Event):
    """Published both when a new watched-contact message first arrives and
    when a snoozed one's timer elapses and it's re-surfaced (see
    service_layer.record_incoming_message / check_due_snoozes) —
    subscribers (notification_adapter.py) don't need to distinguish the
    two, same as modules.calendar.events.ReminderDue doesn't."""

    message_id: int
    source: str
    sender_label: str
    text: str
    received_at: datetime
