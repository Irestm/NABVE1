from __future__ import annotations

from core.message_bus import message_bus
from modules.messaging.events import MessageReceived
from modules.messaging.handlers import register_commands
from modules.messaging.notification_adapter import send_desktop_notification
from modules.messaging.snooze_checker import SnoozeChecker

snooze_checker = SnoozeChecker()

message_bus.subscribe(MessageReceived, send_desktop_notification)

__all__ = ["register_commands", "snooze_checker"]
