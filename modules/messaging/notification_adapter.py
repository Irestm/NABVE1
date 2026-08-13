from __future__ import annotations

import asyncio

from core.logger import get_logger
from modules.calendar.notification_adapter import notify
from modules.messaging.events import MessageReceived

logger = get_logger(__name__)


async def send_desktop_notification(event: MessageReceived) -> None:
    """Message-bus subscriber for MessageReceived — reuses
    modules.calendar.notification_adapter.notify directly (already a
    generic, non-calendar-specific notify-send/MessageBoxW wrapper) rather
    than duplicating the platform-branching logic. Errors here must not
    stop other subscribers from running; the bus itself already isolates
    handler failures, this just logs with a traceback so a genuinely broken
    notify-send install is diagnosable."""
    try:
        await asyncio.to_thread(notify, f"Сообщение от {event.sender_label}", event.text)
    except Exception:
        logger.exception("Failed to show desktop notification for message id=%s", event.message_id)
