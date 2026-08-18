from __future__ import annotations

import asyncio
import ctypes
import platform
import shutil
import subprocess

from core.logger import get_logger
from modules.calendar.events import ReminderDue

logger = get_logger(__name__)


def _require_notify_send() -> None:
    if not shutil.which("notify-send"):
        raise RuntimeError(
            "Desktop notifications require notify-send. Install it with: sudo apt-get install libnotify-bin"
        )


def notify(title: str, message: str) -> None:
    system = platform.system()
    if system == "Linux":
        _require_notify_send()
        subprocess.run(["notify-send", title, message], check=True)
    elif system == "Windows":
        ctypes.windll.user32.MessageBoxW(0, message, title, 0)
    else:
        raise RuntimeError(f"Desktop notifications are not supported on {system}")


async def send_desktop_notification(event: ReminderDue) -> None:
    """Message-bus subscriber for ReminderDue — the OS-notification side of
    reminder delivery. Errors here must not stop other subscribers (e.g.
    core/voice/announcements.py's spoken reminder) from running; the bus
    itself already isolates handler failures, this just logs with a
    traceback so a genuinely broken notify-send install is diagnosable."""
    try:
        await asyncio.to_thread(notify, "Напоминание", event.title)
    except Exception:
        logger.exception("Failed to show desktop notification for event id=%s", event.event_id)
