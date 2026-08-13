from __future__ import annotations

import httpx

from core.config import Settings, settings
from core.logger import get_logger
from modules.calendar.events import ReminderDue
from modules.hardware_adaptive.events import HardwareAlertRaised
from modules.plugin_agent.events import PluginCandidateReadyForReview

logger = get_logger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT_SECONDS = 10.0


class TelegramNotifier:
    """Message-bus subscriber that pushes a short text notification to the
    user's own Telegram (via a Bot API token — see core/config.py's
    telegram_notify_bot_token/telegram_notify_chat_id) for events that
    matter even when nobody's near the mic to hear core/voice's own spoken
    versions (core/voice/announcements.py::ReminderAnnouncer,
    core/voice/proactive_announcer.py::ProactiveAnnouncer).

    Deliberately unrelated to modules/telegram: that module drives a
    personal Telegram *account* via Telethon/MTProto to read incoming
    messages, a different API surface entirely. This one only ever calls
    the plain Bot API to send outbound messages, the same one a companion
    Telegram bot project's own BOT_TOKEN already talks to — reusing that
    same token here is the intended setup (see this class's construction in
    core/bootstrap.py).

    Silently does nothing when not configured — see _configured below —
    same "absent config = feature off" convention as
    modules.ai_bridge.api_providers.GroqApiAdapter, never a hard failure
    for users who don't want this."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self._settings = app_settings

    @property
    def _configured(self) -> bool:
        return bool(self._settings.telegram_notify_bot_token and self._settings.telegram_notify_chat_id)

    async def _send(self, text: str) -> None:
        if not self._configured:
            return
        url = _TELEGRAM_API_URL.format(token=self._settings.telegram_notify_bot_token)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url, json={"chat_id": self._settings.telegram_notify_chat_id, "text": text}
                )
            response.raise_for_status()
        except Exception:
            logger.exception("Failed to send Telegram notification")

    async def handle_reminder(self, event: ReminderDue) -> None:
        await self._send(f"⏰ Напоминание: {event.title}")

    async def handle_hardware_alert(self, event: HardwareAlertRaised) -> None:
        await self._send(f"⚠️ {event.message}")

    async def handle_plugin_candidate(self, event: PluginCandidateReadyForReview) -> None:
        note = (
            " (нужен ручной обзор — сработали проверки безопасности)"
            if event.requires_manual_review
            else ""
        )
        await self._send(
            f"🧩 Новый плагин «{event.plugin_name}» ждёт одобрения{note}. "
            "Открой раздел NABVE в боте, чтобы посмотреть код и одобрить/отклонить."
        )
