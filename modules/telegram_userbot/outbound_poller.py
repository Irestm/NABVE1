from __future__ import annotations

import asyncio

from core.logger import get_logger
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.domain import OutboundMessage
from modules.messaging.uow import MessagingUnitOfWork
from modules.telegram_userbot import client_manager

logger = get_logger(__name__)

_POLL_INTERVAL_SECONDS = 5.0
_running = False


async def _send_one(message: OutboundMessage) -> None:
    assert message.id is not None
    # No per-message account field in modules.messaging's schema (see
    # client_manager.SOURCE's design note) — tries every connected account
    # in turn and uses whichever one Telegram actually accepts the send on,
    # rather than guessing which of the user's own accounts the recipient
    # is reachable from.
    for account_id in client_manager.connected_account_ids():
        delivered = await client_manager.send_message(account_id, message.recipient_identifier, message.text)
        if delivered:
            await asyncio.to_thread(
                messaging_service_layer.mark_outbound_delivered, MessagingUnitOfWork(), message.id, True
            )
            return
    await asyncio.to_thread(
        messaging_service_layer.mark_outbound_delivered, MessagingUnitOfWork(), message.id, False
    )


async def run_forever() -> None:
    global _running
    _running = True
    while _running:
        try:
            pending = await asyncio.to_thread(
                messaging_service_layer.list_pending_outbound, MessagingUnitOfWork()
            )
            for message in pending:
                if message.source == client_manager.SOURCE:
                    await _send_one(message)
        except Exception:
            logger.exception("Telegram outbound poller iteration failed")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def stop() -> None:
    global _running
    _running = False
