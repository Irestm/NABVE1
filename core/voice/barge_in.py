from __future__ import annotations

import threading

from core.logger import get_logger
from core.voice.audio_io import RollingAudioBuffer
from core.voice.config import VoiceSettings
from core.voice.intent import is_stop_command
from core.voice.stt import SpeechToText

logger = get_logger(__name__)

# Short window: barge-in should feel near-instant, unlike the wake-word
# listener's 2s window — the trade-off is a stop phrase split across two
# windows would never match whole, but "стоп"/"stop" (a single short word)
# never spans that long anyway.
_WINDOW_SECONDS = 1.2
_POLL_TIMEOUT_SECONDS = 0.3


class BargeInMonitor:
    """Runs on its own thread alongside TTS playback (see
    VoiceAssistantLoop._speak_safely): listens on a second mic stream for a
    short stop phrase and sets `stop_event` the instant it hears one, so
    playback can be cut off mid-reply instead of finishing it first. Uses the
    same fast whisper_wake_model_size tier as wake-word detection rather than
    the bigger command model — this only ever needs to recognize a couple of
    short words, and speed here directly determines how quickly an
    interruption actually lands.

    Caveat: there's no acoustic echo cancellation anywhere in this codebase,
    so the mic also picks up the assistant's own voice through speaker
    bleed. In practice that's just noise a stop-phrase fuzzy match won't hit
    (wasting a transcribe pass, not a false trigger) — the real risk runs the
    other way: a quiet "стоп" said while a loud reply is playing can get
    drowned out. Works best with a headset, or at least mic/speaker
    positioned so the mic isn't pointed straight at the speaker.
    """

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._stt = SpeechToText(settings, model_size=settings.whisper_wake_model_size)

    def run(self, language: str, stop_event: threading.Event, interrupted: threading.Event) -> None:
        buffer = RollingAudioBuffer(self._settings, window_seconds=_WINDOW_SECONDS)
        try:
            buffer.start()
        except Exception as mic_unavailable:
            logger.debug(
                "Barge-in mic capture unavailable; interruption disabled for this reply: %s",
                mic_unavailable,
                exc_info=True,
            )
            return

        try:
            while not stop_event.is_set():
                window = buffer.read_window(timeout=_POLL_TIMEOUT_SECONDS)
                if window.size == 0:
                    continue
                try:
                    result = self._stt.transcribe(window, language)
                except Exception as transcription_failed:
                    logger.debug("Barge-in transcription failed: %s", transcription_failed, exc_info=True)
                    continue
                if is_stop_command(result.text, language):
                    interrupted.set()
                    stop_event.set()
                    return
        finally:
            buffer.stop()
