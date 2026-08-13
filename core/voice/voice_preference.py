from __future__ import annotations

import json
from pathlib import Path

from core.config import DATA_DIR
from core.logger import get_logger
from core.voice.config import voice_settings
from core.voice.silero_tts import VOICE_SPEAKER_IDS

logger = get_logger(__name__)

# A single local user's TTS voice choice; small enough (one field) that a
# JSON file is simpler than a sqlite-backed repository, and it's read on
# every synthesize() call so a change from the UI takes effect immediately
# without restarting the backend.
_PREFERENCE_PATH: Path = DATA_DIR / "voice_preference.json"


def get_selected_speaker() -> str:
    """The Silero speaker to use right now: the persisted user choice if one
    was ever saved and is still a valid speaker id, else VoiceSettings'
    default (env-overridable, male by default)."""
    try:
        raw = _PREFERENCE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return voice_settings.silero_ru_speaker
    except OSError:
        logger.exception("Failed to read voice preference file at %s", _PREFERENCE_PATH)
        return voice_settings.silero_ru_speaker

    try:
        speaker = json.loads(raw)["speaker"]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.exception("Malformed voice preference file at %s", _PREFERENCE_PATH)
        return voice_settings.silero_ru_speaker

    if speaker not in VOICE_SPEAKER_IDS:
        logger.warning("Persisted voice speaker %r is no longer a known voice; ignoring", speaker)
        return voice_settings.silero_ru_speaker
    return speaker


def set_selected_speaker(speaker: str) -> None:
    if speaker not in VOICE_SPEAKER_IDS:
        raise ValueError(f"Unknown voice speaker: {speaker!r}")
    _PREFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFERENCE_PATH.write_text(json.dumps({"speaker": speaker}), encoding="utf-8")
