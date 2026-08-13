from __future__ import annotations

from core.message_bus import message_bus
from modules.calendar.events import ReminderDue
from modules.calendar.handlers import register_commands
from modules.calendar.notification_adapter import send_desktop_notification
from modules.calendar.notifier import ReminderChecker

reminder_checker = ReminderChecker()

# Desktop notification is calendar's own concern (uses no other module), so
# it's wired here. The voice-announcement subscriber additionally depends on
# core.voice and the running voice loop, so it's composed in
# core/bootstrap.py instead, which is where cross-module wiring belongs.
message_bus.subscribe(ReminderDue, send_desktop_notification)

__all__ = ["register_commands", "reminder_checker"]
