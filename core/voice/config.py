from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from core.config import DATA_DIR
from core.logger import get_logger

VOICES_DIR: Path = DATA_DIR / "voices"

logger = get_logger(__name__)


def _detect_whisper_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        logger.warning("Could not check torch.cuda.is_available(); defaulting whisper_device to cpu", exc_info=True)
        return "cpu"


@dataclass(frozen=True)
class VoiceSettings:
    wake_word: str = os.environ.get("ASSISTANT_WAKE_WORD", "ассистент")
    sample_rate: int = 16000

    whisper_model_size: str = os.environ.get("ASSISTANT_WHISPER_MODEL", "small")
    whisper_wake_model_size: str = os.environ.get("ASSISTANT_WHISPER_WAKE_MODEL", "tiny")
    whisper_device: str = os.environ.get("ASSISTANT_WHISPER_DEVICE") or _detect_whisper_device()
    whisper_compute_type: str = os.environ.get("ASSISTANT_WHISPER_COMPUTE", "int8")

    supported_languages: tuple[str, ...] = ("ru", "uk", "en")
    # This assistant is deployed for a single Russian-speaking user; when
    # Whisper's language detection confidence is too low to trust (below
    # language_confidence_threshold — common for short phrases or a noisy
    # mic), default to Russian rather than English.
    fallback_language: str = "ru"
    # Below this whisper language_probability, the detected language is treated
    # as unreliable and STT input falls back to `fallback_language`.
    language_confidence_threshold: float = 0.6

    # Legacy alias, still read for backwards compatibility with existing deployments.
    forced_language: str | None = os.environ.get("ASSISTANT_FORCED_LANGUAGE") or None
    # If set, TTS always answers in this language regardless of the language
    # detected from the user's speech (which still drives command interpretation).
    response_language_override: str | None = (
        os.environ.get("ASSISTANT_RESPONSE_LANGUAGE_OVERRIDE")
        or os.environ.get("ASSISTANT_FORCED_LANGUAGE")
        or None
    )

    piper_voice_models: dict[str, Path] = field(
        default_factory=lambda: {
            "ru": VOICES_DIR / "ru.onnx",
            "uk": VOICES_DIR / "uk.onnx",
            "en": VOICES_DIR / "en.onnx",
        }
    )
    # Preferred over the Piper "ru" voice above when present — see
    # core/voice/silero_tts.py for what this file is and where to get it.
    # TextToSpeech falls back to Piper automatically if it's missing.
    silero_ru_model_path: Path = VOICES_DIR / "silero_ru_v3.pt"
    # Male by default per explicit request; overridden at runtime by whatever
    # the user picks in the voice-selection UI (see core/voice/voice_preference.py),
    # which persists across restarts and takes priority over this env default.
    silero_ru_speaker: str = os.environ.get("ASSISTANT_SILERO_SPEAKER", "eugene")

    # How long a pause has to last (after real speech has been detected —
    # see core/voice/vad.py) before the assistant treats the user as done
    # talking. Bumped from 2.2s -> 3.5s: for a long dictated message, a
    # natural thinking pause mid-sentence easily runs past 2.2s and was
    # cutting people off before they'd actually finished.
    command_silence_timeout_seconds: float = float(
        os.environ.get("ASSISTANT_COMMAND_SILENCE_TIMEOUT", "3.5")
    )
    # Hard cap regardless of pauses, so a stuck/open mic can't record forever.
    # Bumped from 15s -> 90s: 15s was cutting off longer dictated messages
    # mid-sentence — this is a ceiling for a runaway mic, not a target length,
    # so it can afford to be generous.
    command_max_seconds: float = float(os.environ.get("ASSISTANT_COMMAND_MAX_SECONDS", "90.0"))
    # After a free-text AI answer finishes speaking uninterrupted, how long
    # to keep listening for an unprompted follow-up question before giving
    # up and returning to wake-word waiting — see
    # core/voice/pipeline.py::VoiceAssistantLoop._maybe_continue_free_text.
    # 0 disables this and restores the previous behavior of always
    # requiring the wake word again for the next question.
    follow_up_window_seconds: float = float(
        os.environ.get("ASSISTANT_FOLLOW_UP_WINDOW_SECONDS", "5.0")
    )
    # webrtcvad aggressiveness, 0 (least aggressive about filtering out
    # non-speech, more false positives) to 3 (most aggressive, more false
    # negatives). 2 is a balanced default for a quiet-room desktop mic.
    vad_aggressiveness: int = int(os.environ.get("ASSISTANT_VAD_AGGRESSIVENESS", "2"))
    wake_word_check_interval_seconds: float = 1.0

    wake_word_backend: str = os.environ.get("ASSISTANT_WAKE_WORD_BACKEND", "keyword")
    porcupine_access_key: str | None = os.environ.get("PORCUPINE_ACCESS_KEY")
    porcupine_keyword_path: str | None = os.environ.get("PORCUPINE_KEYWORD_PATH")

    def __post_init__(self) -> None:
        # response_language_override flows unvalidated into every
        # language-keyed lookup downstream — most of them (core/voice/
        # responses.py, core/voice/tts.py) degrade gracefully to English/
        # fallback_language for a key they don't recognize, but
        # core/voice/intent.py's STOP_PHRASES/AFFIRMATIVE_PHRASES (used by
        # is_stop_command/is_affirmative — barge-in "стоп" mid-reply and
        # yes/no confirmation of dangerous commands) do a plain dict.get()
        # with an EMPTY set as the fallback: an override value outside
        # supported_languages (a typo, "RU" uppercase, a locale-style
        # "ru-RU", ...) would silently make both of those permanently
        # unrecognizable for the whole session, with nothing in the logs
        # pointing at why "стоп" stopped working. Catching it once here,
        # at startup, means every downstream reader can keep trusting
        # response_language_override is either None or a real supported
        # language, instead of every call site needing its own guard.
        if (
            self.response_language_override is not None
            and self.response_language_override not in self.supported_languages
        ):
            logger.warning(
                "response_language_override=%r is not one of supported_languages=%r; "
                "ignoring it (falling back to the detected input language). Check "
                "ASSISTANT_RESPONSE_LANGUAGE_OVERRIDE / ASSISTANT_FORCED_LANGUAGE.",
                self.response_language_override,
                self.supported_languages,
            )
            object.__setattr__(self, "response_language_override", None)


voice_settings = VoiceSettings()
