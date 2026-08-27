from __future__ import annotations

import threading

from core.logger import get_logger
from core.voice import special_phrases
from core.voice.audio_io import RollingAudioBuffer
from core.voice.config import VoiceSettings
from core.voice.stt import SpeechToText

logger = get_logger(__name__)

# Short window: barge-in should feel near-instant, unlike the wake-word
# listener's 2s window — the trade-off is a stop phrase split across two
# windows would never match whole, but "стоп"/"stop" (a single short word)
# never spans that long anyway.
_WINDOW_SECONDS = 1.2
_POLL_TIMEOUT_SECONDS = 0.3


class BargeInMonitor:
    """Runs on its own thread alongside TTS playback, "thinking" (any
    run_cancellable call), or the user's own command being recorded (see
    VoiceAssistantLoop._speak_safely, run_cancellable, and
    _record_command_audio respectively): listens on a second mic stream for
    the user's own configured stop word (core/voice/special_phrases.py's
    "pause" entry — the same word _wait_for_wake_or_pause listens for, not
    the fixed STOP_PHRASES list this used to check via is_stop_command) and
    sets `stop_event` the instant it hears it, so whatever's currently
    happening can be cut short instead of running to completion first. Uses
    the same fast whisper_wake_model_size tier as wake-word detection rather
    than the bigger command model — this only ever needs to recognize a
    short phrase, and speed here directly determines how quickly an
    interruption actually lands.

    Hearing the stop word here means the same thing it means everywhere
    else: a full pause, not "cut off and keep listening" — see
    VoiceAssistantLoop._run, which sets AssistantState.PAUSED once this
    monitor's `interrupted` fires, exactly like _wait_for_wake_or_pause's own
    "pause" branch.

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

    def run(
        self,
        language: str,
        stop_event: threading.Event,
        interrupted: threading.Event,
        *,
        context: str = "speaking",
    ) -> None:
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
                if special_phrases.check(result.text, context, self._settings) == "pause":
                    interrupted.set()
                    stop_event.set()
                    return
        finally:
            buffer.stop()
