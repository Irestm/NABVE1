from __future__ import annotations

from datetime import datetime, timedelta

from core.message_bus import MessageBus
from modules.messaging.domain import PendingMessage, PendingMessageStatus, WatchedContact
from modules.messaging.events import MessageReceived
from modules.messaging.uow import MessagingUnitOfWork

_MERGE_SEPARATOR = "\n"


def _normalize_identifier(identifier: str) -> str:
    """@username/phone comparisons should be exact-after-normalization
    (case, an optional leading '@'), not fuzzy — unlike matching a spoken
    sender name against pending messages (core/voice/pipeline.py's
    _resolve_pending_message_target, which genuinely deals with natural
    speech/STT output), a Telegram identifier is a literal string on both
    sides of the comparison."""
    return identifier.strip().lstrip("@").lower()


def add_watched_contact(uow: MessagingUnitOfWork, source: str, identifier: str, note: str = "") -> int:
    with uow:
        contact_id = uow.contacts.add(
            WatchedContact(source=source, identifier=_normalize_identifier(identifier), note=note)
        )
        uow.commit()
    return contact_id


def list_watched_contacts(uow: MessagingUnitOfWork) -> list[WatchedContact]:
    with uow:
        return uow.contacts.list_all()


def remove_watched_contact(uow: MessagingUnitOfWork, contact_id: int) -> bool:
    with uow:
        removed = uow.contacts.delete(contact_id)
        uow.commit()
    return removed


def record_incoming_message(
    uow: MessagingUnitOfWork, source: str, sender_identifier: str, sender_label: str, text: str
) -> PendingMessage | None:
    """Stores an inbound message ONLY if its sender is on the watch list —
    everything else is deliberately never even persisted, keeping the
    table limited to what the user actually asked to track. Returns None
    (a no-op) for an unwatched sender.

    If there's already an active (PENDING or SNOOZED) row for this exact
    contact, merges the new text into it instead of creating a second row
    per contact: a SNOOZED row is bumped back to PENDING (new content
    deserves fresh attention over an old snooze timer, not silent
    absorption into it), a PENDING row just gets the new text appended and
    received_at bumped."""
    identifier = _normalize_identifier(sender_identifier)
    with uow:
        contact = uow.contacts.find(source, identifier)
        if contact is None:
            return None

        existing = uow.messages.find_active(source, identifier)
        if existing is not None:
            existing.text = f"{existing.text}{_MERGE_SEPARATOR}{text}" if existing.text else text
            existing.received_at = datetime.now()
            existing.status = PendingMessageStatus.PENDING
            existing.snooze_until = None
            uow.messages.update(existing)
            uow.commit()
            return existing

        pending = PendingMessage(
            source=source, sender_identifier=identifier, sender_label=sender_label, text=text
        )
        pending.id = uow.messages.add(pending)
        uow.commit()
        return pending


def list_pending(uow: MessagingUnitOfWork) -> list[PendingMessage]:
    with uow:
        return uow.messages.list_pending()


def get_message(uow: MessagingUnitOfWork, message_id: int) -> PendingMessage | None:
    with uow:
        return uow.messages.get(message_id)


def mark_replied(uow: MessagingUnitOfWork, message_id: int) -> bool:
    with uow:
        message = uow.messages.get(message_id)
        if message is None:
            return False
        message.status = PendingMessageStatus.REPLIED
        uow.messages.update(message)
        uow.commit()
        return True


def snooze(uow: MessagingUnitOfWork, message_id: int, minutes: int) -> bool:
    with uow:
        message = uow.messages.get(message_id)
        if message is None:
            return False
        message.status = PendingMessageStatus.SNOOZED
        message.snooze_until = datetime.now() + timedelta(minutes=minutes)
        uow.messages.update(message)
        uow.commit()
        return True


async def notify_new_message(bus: MessageBus, pending: PendingMessage) -> None:
    assert pending.id is not None
    assert pending.received_at is not None
    await bus.publish(
        MessageReceived(
            message_id=pending.id,
            source=pending.source,
            sender_label=pending.sender_label,
            text=pending.text,
            received_at=pending.received_at,
        )
    )


async def check_due_snoozes(uow: MessagingUnitOfWork, bus: MessageBus, now: datetime | None = None) -> int:
    """Finds SNOOZED messages whose timer has elapsed, flips them back to
    PENDING, and re-publishes MessageReceived for each — mirrors
    modules.calendar.service_layer.check_due_reminders exactly: mark done
    and commit first, then publish outside the `with uow` block, so a
    slow or failing subscriber can never hold up the DB write."""
    now = now or datetime.now()
    with uow:
        due = uow.messages.list_due_snoozes(now)
        for message in due:
            message.status = PendingMessageStatus.PENDING
            message.snooze_until = None
            uow.messages.update(message)
        uow.commit()

    for message in due:
        await notify_new_message(bus, message)

    return len(due)
