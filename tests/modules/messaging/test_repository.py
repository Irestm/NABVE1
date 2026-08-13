from __future__ import annotations

from datetime import datetime, timedelta

from modules.messaging.domain import PendingMessage, PendingMessageStatus, WatchedContact
from modules.messaging.uow import MessagingUnitOfWork


def test_watched_contact_add_get_find(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    with uow:
        contact_id = uow.contacts.add(WatchedContact(source="telegram", identifier="@ira", note="сестра"))
        uow.commit()

    with uow:
        stored = uow.contacts.get(contact_id)
        assert stored is not None
        assert stored.identifier == "@ira"
        assert stored.note == "сестра"
        assert stored.created_at is not None

        found = uow.contacts.find("telegram", "@ira")
        assert found is not None and found.id == contact_id
        assert uow.contacts.find("telegram", "@nobody") is None


def test_watched_contact_delete(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    with uow:
        contact_id = uow.contacts.add(WatchedContact(source="telegram", identifier="@ira"))
        uow.commit()
    with uow:
        assert uow.contacts.delete(contact_id) is True
        uow.commit()
    with uow:
        assert uow.contacts.get(contact_id) is None
        assert uow.contacts.delete(contact_id) is False


def test_pending_message_add_get_list_pending(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    with uow:
        msg_id = uow.messages.add(
            PendingMessage(source="telegram", sender_identifier="@ira", sender_label="Ира", text="привет")
        )
        uow.commit()

    with uow:
        stored = uow.messages.get(msg_id)
        assert stored is not None
        assert stored.status == PendingMessageStatus.PENDING
        assert stored.received_at is not None

        pending = uow.messages.list_pending()
        assert [m.id for m in pending] == [msg_id]


def test_find_active_matches_pending_and_snoozed_not_replied(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    with uow:
        pending_id = uow.messages.add(
            PendingMessage(source="telegram", sender_identifier="@a", sender_label="A", text="1")
        )
        replied = uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="@b",
                sender_label="B",
                text="2",
                status=PendingMessageStatus.REPLIED,
            )
        )
        snoozed_id = uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="@c",
                sender_label="C",
                text="3",
                status=PendingMessageStatus.SNOOZED,
                snooze_until=datetime.now() + timedelta(minutes=10),
            )
        )
        uow.commit()

    with uow:
        assert uow.messages.find_active("telegram", "@a") is not None
        assert uow.messages.find_active("telegram", "@a").id == pending_id
        assert uow.messages.find_active("telegram", "@b") is None  # replied -> not active
        assert uow.messages.find_active("telegram", "@c").id == snoozed_id
        assert uow.messages.find_active("telegram", "@nobody") is None
        assert replied  # keep flake8 quiet about the unused-looking local


def test_list_due_snoozes(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    now = datetime.now()
    with uow:
        due_id = uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="@due",
                sender_label="Due",
                text="x",
                status=PendingMessageStatus.SNOOZED,
                snooze_until=now - timedelta(minutes=1),
            )
        )
        uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="@notyet",
                sender_label="Not yet",
                text="y",
                status=PendingMessageStatus.SNOOZED,
                snooze_until=now + timedelta(minutes=30),
            )
        )
        uow.commit()

    with uow:
        due = uow.messages.list_due_snoozes(now)
        assert [m.id for m in due] == [due_id]


def test_update_changes_text_status_and_snooze_until(tmp_path) -> None:
    uow = MessagingUnitOfWork(tmp_path / "assistant.db")
    with uow:
        msg_id = uow.messages.add(
            PendingMessage(source="telegram", sender_identifier="@a", sender_label="A", text="first")
        )
        uow.commit()

    with uow:
        stored = uow.messages.get(msg_id)
        stored.text = "first\nsecond"
        stored.status = PendingMessageStatus.SNOOZED
        stored.snooze_until = datetime.now() + timedelta(minutes=15)
        uow.messages.update(stored)
        uow.commit()

    with uow:
        updated = uow.messages.get(msg_id)
        assert updated.text == "first\nsecond"
        assert updated.status == PendingMessageStatus.SNOOZED
        assert updated.snooze_until is not None
