from __future__ import annotations

import asyncio

from core.logger import get_logger
from core.models import AssistantState
from core.state import state_manager
from core.voice.config import VoiceSettings, voice_settings
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.tts import TextToSpeech
from modules.hardware_adaptive.events import HardwareAlertRaised

logger = get_logger(__name__)

# Speaking an unprompted notification mid-turn would step on whatever the
# assistant is already doing (answering a question, running the onboarding
# interview) — these states mean "leave it alone, the next poll will try
# again if the condition is still true", not "queue and interrupt".
_BUSY_STATES = frozenset(
    {AssistantState.SPEAKING, AssistantState.PROCESSING, AssistantState.ONBOARDING}
)


class ProactiveAnnouncer:
    """Message-bus subscriber for unprompted spoken notifications —
    currently HardwareAlertRaised (see modules/hardware_adaptive/events.py),
    with more proactive event sources expected to subscribe here later.
    Same "only while the voice loop is running" gate as
    core.voice.announcements.ReminderAnnouncer, plus a busy-state check:
    unprompted alerts are more likely than a scheduled calendar reminder to
    land while the user is already mid-conversation with the assistant."""

    def __init__(self, voice_loop: VoiceAssistantLoop, settings: VoiceSettings = voice_settings) -> None:
        self._voice_loop = voice_loop
        self._settings = settings
        self._tts: TextToSpeech | None = None

    async def handle(self, event: HardwareAlertRaised) -> None:
        if not self._voice_loop.is_running:
            return
        if state_manager.state in _BUSY_STATES:
            return
        if self._tts is None:
            self._tts = TextToSpeech(self._settings)

        language = self._settings.response_language_override or "ru"
        try:
            await asyncio.to_thread(self._tts.speak, event.message, language)
        except Exception:
            logger.exception("Failed to speak hardware alert metric=%s", event.metric)
