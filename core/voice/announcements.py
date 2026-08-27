from __future__ import annotations

import asyncio

from core.logger import get_logger
from core.state import state_manager
from core.voice.config import VoiceSettings, voice_settings
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.proactive_announcer import BUSY_STATES
from core.voice.tts import TextToSpeech
from modules.calendar.events import ReminderDue

logger = get_logger(__name__)


class ReminderAnnouncer:
    """Message-bus subscriber for ReminderDue: speaks the reminder aloud,
    but only while the voice loop is actually running — a reminder firing
    while the assistant isn't listening should still get its desktop
    notification (modules/calendar/notification_adapter.py), just not an
    unprompted voice interruption. Composed in core/bootstrap.py since it
    depends on both modules.calendar and core.voice.

    Also skips while the assistant is mid-turn (same BUSY_STATES gate as
    core.voice.proactive_announcer.ProactiveAnnouncer) — a scheduled
    reminder landing while the user is already talking to the assistant
    used to speak right over/into that conversation (audio_io.play_audio
    has no lock, so a second concurrent sd.play() call stomps on whatever
    the first one was doing instead of queuing or mixing). The reminder's
    desktop notification still fires either way; only the voice
    announcement is skipped for that one reminder."""

    def __init__(self, voice_loop: VoiceAssistantLoop, settings: VoiceSettings = voice_settings) -> None:
        self._voice_loop = voice_loop
        self._settings = settings
        self._tts: TextToSpeech | None = None

    async def handle(self, event: ReminderDue) -> None:
        if not self._voice_loop.is_running:
            return
        if state_manager.state in BUSY_STATES:
            return
        if self._tts is None:
            self._tts = TextToSpeech(self._settings)

        language = self._settings.response_language_override or "ru"
        text = f"Напоминание: {event.title}"
        try:
            await asyncio.to_thread(self._tts.speak, text, language)
        except Exception:
            logger.exception("Failed to speak reminder for event id=%s", event.event_id)
