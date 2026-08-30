from __future__ import annotations

import asyncio
import threading

from core.logger import get_logger
from core.models import AssistantState
from core.state import state_manager
from core.voice import audio_io
from core.voice.config import VoiceSettings, voice_settings
from core.voice.intent import is_affirmative
from core.voice.phrase_matching import fuzzy_matches_any
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.tts import TextToSpeech
from modules.calendar.events import ReminderDue

logger = get_logger(__name__)

# "any acknowledgement phrase" per the spec — is_affirmative covers "да /
# подтверждаю / согласен", these cover the rest a person actually says to
# dismiss an alert.
_ACK_PHRASES: dict[str, set[str]] = {
    "ru": {"понял", "поняла", "принято", "хорошо", "ок", "окей", "услышал", "услышала", "спасибо"},
    "uk": {"зрозумів", "зрозуміла", "прийнято", "добре", "ок", "дякую"},
    "en": {"got it", "ok", "okay", "understood", "acknowledged", "thanks", "noted"},
}

_MAX_ACK_ATTEMPTS = 5


class CriticalReminderHandler:
    """Message-bus subscriber for ReminderDue where `critical` is set. Takes
    over the assistant: pauses any playing media, switches the orb to its
    attention state, speaks the reminder, and waits for a spoken
    acknowledgement before resuming media and returning to normal. Composed
    in core/bootstrap.py (needs both modules.calendar and core.voice). A
    non-critical reminder is left entirely to
    core.voice.announcements.ReminderAnnouncer.

    v1 scope: this does not freeze the mic loop thread — it relies on the
    CRITICAL_REMINDER state plus the rarity of a critical reminder firing at
    the exact same moment as a command turn. The media pause/resume and the
    blocking acknowledgement wait are the load-bearing parts."""

    def __init__(self, voice_loop: VoiceAssistantLoop, settings: VoiceSettings = voice_settings) -> None:
        self._voice_loop = voice_loop
        self._settings = settings
        self._tts: TextToSpeech | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    async def handle(self, event: ReminderDue) -> None:
        if not event.critical:
            return
        if not self._voice_loop.is_running:
            # Not listening — the desktop notification (calendar's own
            # subscriber) still fires; a takeover with nobody to acknowledge
            # it would just leave media paused indefinitely.
            return
        if not self._lock.acquire(blocking=False):
            logger.info("Critical reminder already in progress, skipping event id=%s", event.event_id)
            return
        try:
            await asyncio.to_thread(self._run_takeover, event)
        finally:
            self._lock.release()

    def _run_takeover(self, event: ReminderDue) -> None:
        from core.os_adapter import get_os_adapter

        if self._tts is None:
            self._tts = TextToSpeech(self._settings)
        language = self._settings.response_language_override or "ru"
        adapter = get_os_adapter()

        try:
            paused = adapter.pause_media()
        except Exception:
            logger.exception("Critical reminder: pause_media failed")
            paused = []

        previous_state = state_manager.state
        state_manager.set_state(AssistantState.CRITICAL_REMINDER, "Критическое напоминание")
        try:
            self._speak(f"У вас запланировано: {event.title}", language)
            self._wait_for_acknowledgement(language)
        finally:
            try:
                adapter.resume_media(paused)
            except Exception:
                logger.exception("Critical reminder: resume_media failed")
            state_manager.set_state(
                previous_state if previous_state != AssistantState.CRITICAL_REMINDER else AssistantState.IDLE
            )

    def _speak(self, text: str, language: str) -> None:
        try:
            assert self._tts is not None
            self._tts.speak(text, language)
        except Exception:
            logger.exception("Critical reminder: TTS failed for %r", text)

    def _wait_for_acknowledgement(self, language: str) -> None:
        from core.voice import web_pipeline

        for attempt in range(_MAX_ACK_ATTEMPTS):
            audio = audio_io.record_until_silence(self._settings, self._stop_event)
            if getattr(audio, "size", 0) == 0:
                self._speak("Скажите «понял», чтобы продолжить.", language)
                continue
            try:
                text = web_pipeline._stt.transcribe(audio).text
            except Exception:
                logger.exception("Critical reminder: STT failed while waiting for acknowledgement")
                text = ""
            if _is_acknowledgement(text, language):
                self._speak("Принято.", language)
                return
            if attempt < _MAX_ACK_ATTEMPTS - 1:
                self._speak("Скажите «понял», чтобы продолжить.", language)
        logger.warning("Critical reminder: no acknowledgement after %d attempts, releasing", _MAX_ACK_ATTEMPTS)


def _is_acknowledgement(text: str, language: str) -> bool:
    if not text or not text.strip():
        return False
    if is_affirmative(text, language):
        return True
    return fuzzy_matches_any(text.lower(), _ACK_PHRASES.get(language, set()))
