from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PendingMessageStatus(str, Enum):
    PENDING = "pending"
    REPLIED = "replied"
    SNOOZED = "snoozed"


class OutboundStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass
class WatchedContact:
    source: str  # only "telegram" this round, kept as a plain string (not
    # an enum) so a future source doesn't need a schema migration to add.
    identifier: str  # e.g. a Telegram @username or phone — exactly what
    # Telethon's client.get_entity() itself needs, not a display name.
    note: str = ""
    id: int | None = None
    created_at: datetime | None = None


@dataclass
class PendingMessage:
    """One contact's not-yet-handled inbound message. At most one
    PENDING-or-SNOOZED row exists per (source, sender_identifier) at a
    time — see service_layer.record_incoming_message, which merges new
    text into the existing row instead of creating a second one."""

    source: str
    sender_identifier: str
    sender_label: str
    text: str
    id: int | None = None
    received_at: datetime | None = None
    status: PendingMessageStatus = PendingMessageStatus.PENDING
    snooze_until: datetime | None = None


@dataclass
class OutboundMessage:
    """A reply queued for an external process to actually deliver — NABVE1
    has no Telegram client of its own (see modules/messaging/BRIDGE.md), so
    _handle_reply in handlers.py just writes a row here instead of sending
    anything itself. A separate bot process polls for PENDING rows, sends
    them, and flips status to SENT/FAILED."""

    source: str
    recipient_identifier: str
    text: str
    id: int | None = None
    created_at: datetime | None = None
    status: OutboundStatus = OutboundStatus.PENDING
    sent_at: datetime | None = None
