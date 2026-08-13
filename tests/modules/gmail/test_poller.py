from __future__ import annotations

from core.message_bus import MessageBus
from modules.gmail import client as gmail_client
from modules.gmail.poller import GmailPoller
from modules.gmail.uow import GmailUnitOfWork
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.events import MessageReceived
from modules.messaging.uow import MessagingUnitOfWork


def _poller(tmp_path, bus: MessageBus | None = None) -> tuple[GmailPoller, callable, callable]:
    def gmail_uow_factory() -> GmailUnitOfWork:
        return GmailUnitOfWork(tmp_path / "assistant.db")

    def messaging_uow_factory() -> MessagingUnitOfWork:
        return MessagingUnitOfWork(tmp_path / "assistant.db")

    poller = GmailPoller(
        gmail_uow_factory=gmail_uow_factory,
        messaging_uow_factory=messaging_uow_factory,
        bus=bus or MessageBus(),
    )
    return poller, gmail_uow_factory, messaging_uow_factory


def test_check_once_skips_silently_when_credentials_missing(monkeypatch, tmp_path) -> None:
    poller, *_ = _poller(tmp_path)
    monkeypatch.setattr(
        gmail_client, "ensure_credentials", lambda: (_ for _ in ()).throw(RuntimeError("no creds"))
    )
    poller._check_once()  # must not raise


def test_check_once_skips_when_no_gmail_contacts_watched(monkeypatch, tmp_path) -> None:
    poller, gmail_uow_factory, _ = _poller(tmp_path)
    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())
    monkeypatch.setattr(gmail_client, "build_service", lambda creds: object())

    poller._check_once()

    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() is None


def test_check_once_sets_initial_cursor_on_first_run(monkeypatch, tmp_path) -> None:
    poller, gmail_uow_factory, messaging_uow_factory = _poller(tmp_path)
    messaging_service_layer.add_watched_contact(messaging_uow_factory(), "gmail", "ira@example.com")

    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())
    monkeypatch.setattr(gmail_client, "build_service", lambda creds: object())
    monkeypatch.setattr(gmail_client, "get_current_history_id", lambda service: "500")

    poller._check_once()

    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() == "500"
    assert messaging_service_layer.list_pending(messaging_uow_factory()) == []


def test_check_once_records_and_notifies_watched_sender(monkeypatch, tmp_path) -> None:
    bus = MessageBus()
    received: list[MessageReceived] = []

    async def handler(event: MessageReceived) -> None:
        received.append(event)

    bus.subscribe(MessageReceived, handler)

    poller, gmail_uow_factory, messaging_uow_factory = _poller(tmp_path, bus)
    messaging_service_layer.add_watched_contact(messaging_uow_factory(), "gmail", "ira@example.com")
    with gmail_uow_factory() as uow:
        uow.sync_state.set_last_history_id("100")
        uow.commit()

    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())
    monkeypatch.setattr(gmail_client, "build_service", lambda creds: object())
    monkeypatch.setattr(
        gmail_client,
        "list_new_messages",
        lambda service, start_history_id: (
            [
                {
                    "id": "m1",
                    "from_email": "ira@example.com",
                    "from_name": "Ira",
                    "subject": "Hi",
                    "snippet": "hello",
                },
                {
                    "id": "m2",
                    "from_email": "stranger@example.com",
                    "from_name": "Stranger",
                    "subject": "x",
                    "snippet": "y",
                },
            ],
            "200",
        ),
    )

    poller._check_once()

    pending = messaging_service_layer.list_pending(messaging_uow_factory())
    assert len(pending) == 1
    assert pending[0].sender_identifier == "ira@example.com"
    assert pending[0].text == "Hi\nhello"
    assert len(received) == 1
    assert received[0].source == "gmail"

    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() == "200"


def test_check_once_does_not_duplicate_text_when_a_later_message_fails(monkeypatch, tmp_path) -> None:
    """Regression: the cursor only advances once every message in the batch
    is recorded — if message 2 fails, the next tick re-fetches the exact
    same batch (same cursor). Without per-message dedup, re-recording
    message 1 would append its subject/snippet into the same PendingMessage
    row a second time (see service_layer.record_incoming_message's merge
    behavior). This runs _check_once TWICE over the same two-message batch,
    the second message failing both times, and asserts message 1's text
    never gets duplicated."""
    poller, gmail_uow_factory, messaging_uow_factory = _poller(tmp_path)
    messaging_service_layer.add_watched_contact(messaging_uow_factory(), "gmail", "ira@example.com")
    with gmail_uow_factory() as uow:
        uow.sync_state.set_last_history_id("100")
        uow.commit()

    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())
    monkeypatch.setattr(gmail_client, "build_service", lambda creds: object())
    monkeypatch.setattr(
        gmail_client,
        "list_new_messages",
        lambda service, start_history_id: (
            [
                {
                    "id": "m1",
                    "from_email": "ira@example.com",
                    "from_name": "Ira",
                    "subject": "Hi",
                    "snippet": "hello",
                },
                {
                    "id": "m2",
                    "from_email": "ira@example.com",
                    "from_name": "Ira",
                    "subject": "Hi again",
                    "snippet": "still there?",
                },
            ],
            "200",
        ),
    )

    original_record_incoming_message = messaging_service_layer.record_incoming_message
    call_count = {"m2": 0}

    def flaky_record(uow, source, sender_identifier, sender_label, text):
        # m1 always succeeds; m2 fails on its first appearance in each of
        # the two _check_once calls below, simulating a transient DB error
        # partway through the batch.
        if "still there?" in text or "Hi again" in text:
            call_count["m2"] += 1
            if call_count["m2"] == 1:
                raise RuntimeError("simulated transient failure")
        return original_record_incoming_message(uow, source, sender_identifier, sender_label, text)

    monkeypatch.setattr(messaging_service_layer, "record_incoming_message", flaky_record)

    poller._check_once()  # m1 recorded, m2 fails -> cursor NOT advanced
    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() == "100"

    poller._check_once()  # same batch re-fetched; m1 must be skipped this time
    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() == "200"  # now advances

    pending = messaging_service_layer.list_pending(messaging_uow_factory())
    assert len(pending) == 1
    assert pending[0].text == "Hi\nhello\nHi again\nstill there?"  # m1's text appears once


def test_check_once_resyncs_from_now_on_history_expired(monkeypatch, tmp_path) -> None:
    poller, gmail_uow_factory, messaging_uow_factory = _poller(tmp_path)
    messaging_service_layer.add_watched_contact(messaging_uow_factory(), "gmail", "ira@example.com")
    with gmail_uow_factory() as uow:
        uow.sync_state.set_last_history_id("stale")
        uow.commit()

    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())
    monkeypatch.setattr(gmail_client, "build_service", lambda creds: object())

    def raise_expired(service, start_history_id):
        raise gmail_client.GmailHistoryExpired("stale")

    monkeypatch.setattr(gmail_client, "list_new_messages", raise_expired)
    monkeypatch.setattr(gmail_client, "get_current_history_id", lambda service: "fresh-cursor")

    poller._check_once()

    with gmail_uow_factory() as uow:
        assert uow.sync_state.get_last_history_id() == "fresh-cursor"


def test_check_once_swallows_unexpected_errors(monkeypatch, tmp_path) -> None:
    poller, _, messaging_uow_factory = _poller(tmp_path)
    messaging_service_layer.add_watched_contact(messaging_uow_factory(), "gmail", "ira@example.com")

    monkeypatch.setattr(gmail_client, "ensure_credentials", lambda: object())

    def raise_unexpected(creds):
        raise RuntimeError("boom")

    monkeypatch.setattr(gmail_client, "build_service", raise_unexpected)

    poller._check_once()  # must not raise
