from __future__ import annotations

import asyncio
import threading
from typing import Callable

from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.gmail import client as gmail_client
from modules.gmail.uow import GmailUnitOfWork
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.domain import PendingMessage
from modules.messaging.uow import MessagingUnitOfWork

logger = get_logger(__name__)


class GmailPoller:
    """Background poller mirroring modules.messaging.snooze_checker.SnoozeChecker
    and modules.calendar.notifier.ReminderChecker's exact thread shape.
    Polls rather than pushes — Gmail push delivery needs a Google Cloud
    Pub/Sub webhook, excessive infrastructure for a local single-user app.
    Read-only: watches modules.messaging's contacts with source == "gmail"
    and turns new mail from them into the same PendingMessage/notification
    pipeline Telegram already uses — no reply/dictation, per the original
    "email stays read-only" constraint (see modules.messaging.handlers'
    source guard on messaging_reply)."""

    def __init__(
        self,
        interval_seconds: int = 60,
        gmail_uow_factory: Callable[[], GmailUnitOfWork] = GmailUnitOfWork,
        messaging_uow_factory: Callable[[], MessagingUnitOfWork] = MessagingUnitOfWork,
        bus: MessageBus = message_bus,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._gmail_uow_factory = gmail_uow_factory
        self._messaging_uow_factory = messaging_uow_factory
        self._bus = bus
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gmail-poller")
        self._thread.start()
        logger.info("Gmail poller started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Gmail poller stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._check_once()
            self._stop_event.wait(self._interval_seconds)

    def _check_once(self) -> None:
        try:
            creds = gmail_client.ensure_credentials()
        except RuntimeError:
            # Not configured yet — same silent degrade as TelegramWatcher
            # with no stored session: nothing to poll until
            # python -m modules.gmail.login has been run once.
            return
        except Exception:
            logger.exception("Gmail poller: failed to load Gmail credentials")
            return

        try:
            watched_emails = self._watched_gmail_emails()
            if not watched_emails:
                return

            service = gmail_client.build_service(creds)
            cursor = self._get_cursor()

            if cursor is None:
                # First-ever run: start from "now" rather than backfilling
                # the whole mailbox history.
                self._set_cursor(gmail_client.get_current_history_id(service))
                return

            try:
                messages, new_cursor = gmail_client.list_new_messages(service, cursor)
            except gmail_client.GmailHistoryExpired:
                logger.warning("Gmail poller: stored historyId expired; resyncing from now")
                self._set_cursor(gmail_client.get_current_history_id(service))
                return

            # Messages already recorded from an earlier attempt at this same
            # cursor position (see _record_message) — the cursor only
            # advances once every message in the batch succeeds, so a
            # failure partway through means the next tick re-fetches the
            # exact same batch from Gmail. Without this, re-recording an
            # already-handled message would append its subject/snippet into
            # the same PendingMessage row a second time (see
            # service_layer.record_incoming_message's merge behavior).
            already_processed = self._get_processed_message_ids()

            newly_pending: list[PendingMessage] = []
            for message in messages:
                if message["id"] in already_processed:
                    continue
                if message["from_email"].strip().lower() not in watched_emails:
                    continue
                pending = self._record_message(message)
                self._mark_processed(message["id"])
                if pending is not None:
                    newly_pending.append(pending)
            self._set_cursor(new_cursor)

            if newly_pending:
                asyncio.run(self._notify_all(newly_pending))
        except Exception:
            logger.exception("Gmail poller: error during poll tick")

    def _record_message(self, message: dict[str, str]) -> PendingMessage | None:
        text = f"{message['subject']}\n{message['snippet']}".strip() if message["subject"] else message["snippet"]
        return messaging_service_layer.record_incoming_message(
            self._messaging_uow_factory(), "gmail", message["from_email"], message["from_name"], text
        )

    def _watched_gmail_emails(self) -> set[str]:
        contacts = messaging_service_layer.list_watched_contacts(self._messaging_uow_factory())
        return {contact.identifier for contact in contacts if contact.source == "gmail"}

    def _get_cursor(self) -> str | None:
        with self._gmail_uow_factory() as uow:
            return uow.sync_state.get_last_history_id()

    def _set_cursor(self, value: str) -> None:
        # Clears processed_message_ids along with advancing the cursor:
        # once history moves past this batch, the History API can never
        # return these same message ids again, so there's nothing left for
        # that set to protect against — see the schema migration's own
        # comment in modules/gmail/repository.py.
        with self._gmail_uow_factory() as uow:
            uow.sync_state.set_last_history_id_and_clear_processed(value)
            uow.commit()

    def _get_processed_message_ids(self) -> set[str]:
        with self._gmail_uow_factory() as uow:
            return uow.sync_state.get_processed_message_ids()

    def _mark_processed(self, message_id: str) -> None:
        with self._gmail_uow_factory() as uow:
            uow.sync_state.add_processed_message_id(message_id)
            uow.commit()

    async def _notify_all(self, pending_messages: list[PendingMessage]) -> None:
        for pending in pending_messages:
            await messaging_service_layer.notify_new_message(self._bus, pending)


gmail_poller = GmailPoller()
