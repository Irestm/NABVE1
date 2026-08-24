from __future__ import annotations

import asyncio

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from core.logger import get_logger
from core.message_bus import message_bus
from core.secret_store import get_secret
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.uow import MessagingUnitOfWork
from modules.telegram_userbot import login
from modules.telegram_userbot.domain import TelegramAccount
from modules.telegram_userbot.uow import TelegramUserbotUnitOfWork

logger = get_logger(__name__)

# Not per-account (see modules/telegram_userbot/__init__.py's design note):
# a watched contact is watched regardless of which of the user's own
# accounts they happen to message, so every connected account forwards
# into the same modules.messaging source/identifier space. Which account a
# message arrived on is folded into sender_label instead (see
# _forward_incoming), not a separate schema field.
SOURCE = "telegram"

_clients: dict[int, TelegramClient] = {}


def connected_account_ids() -> list[int]:
    return list(_clients.keys())


async def _forward_incoming(account: TelegramAccount, event: "events.NewMessage.Event") -> None:
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    identifier = getattr(sender, "username", None) or str(sender.id)
    display_name = (
        " ".join(
            part
            for part in (getattr(sender, "first_name", None), getattr(sender, "last_name", None))
            if part
        )
        or identifier
    )
    label = f"{display_name} ({account.label})" if account.label else display_name

    pending = await asyncio.to_thread(
        messaging_service_layer.record_incoming_message,
        MessagingUnitOfWork(),
        SOURCE,
        identifier,
        label,
        event.raw_text or "",
    )
    if pending is not None:
        await messaging_service_layer.notify_new_message(message_bus, pending)


async def connect_account(account: TelegramAccount) -> bool:
    """Starts (or reuses) a live client for this account and registers its
    new-message listener. Best-effort: returns False without raising if app
    credentials or this account's stored session are missing/invalid, so a
    broken account can't take down the others (see connect_all_stored_accounts,
    called once at startup for every stored row)."""
    if account.id in _clients:
        return True
    credentials = login.get_app_credentials()
    session_string = get_secret(account.session_secret_name)
    if credentials is None or not session_string:
        logger.warning("Cannot connect Telegram account '%s': missing credentials/session", account.label)
        return False
    api_id, api_hash = credentials
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Stored session for Telegram account '%s' is no longer valid", account.label)
            await client.disconnect()
            return False
    except Exception:
        logger.exception("Failed to connect Telegram account '%s'", account.label)
        return False

    client.add_event_handler(
        lambda event: _forward_incoming(account, event), events.NewMessage(incoming=True)
    )
    _clients[account.id] = client
    logger.info("Connected Telegram userbot account '%s'", account.label)
    return True


async def disconnect_account(account_id: int) -> None:
    client = _clients.pop(account_id, None)
    if client is not None:
        await client.disconnect()


async def connect_all_stored_accounts() -> None:
    with TelegramUserbotUnitOfWork() as uow:
        accounts = uow.accounts.list_all()
    for account in accounts:
        await connect_account(account)


async def send_message(account_id: int, recipient_identifier: str, text: str) -> bool:
    client = _clients.get(account_id)
    if client is None:
        return False
    try:
        await client.send_message(recipient_identifier, text)
        return True
    except Exception:
        logger.exception("Failed to send Telegram message via account id=%s", account_id)
        return False
