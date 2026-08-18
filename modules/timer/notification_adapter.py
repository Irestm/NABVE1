from __future__ import annotations

import asyncio

from core.logger import get_logger
from modules.calendar.notification_adapter import notify
from modules.timer.events import TimerFired

logger = get_logger(__name__)


async def send_desktop_notification(event: TimerFired) -> None:
    """Message-bus subscriber for TimerFired — reuses
    modules.calendar.notification_adapter.notify (a plain OS-notification
    function, not actually calendar-specific) instead of duplicating the
    notify-send/MessageBoxW logic here."""
    try:
        await asyncio.to_thread(notify, event.label, "Время вышло.")
    except Exception:
        logger.exception("Failed to show desktop notification for timer id=%s", event.timer_id)
