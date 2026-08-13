from __future__ import annotations

from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.voice.config import voice_settings
from core.voice.stt import SpeechToText

logger = get_logger(__name__)


def decode_audio_file(path: str) -> Any:
    try:
        from faster_whisper.audio import decode_audio
    except ImportError:
        try:
            from faster_whisper import decode_audio
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper's audio decoding helper (decode_audio) was not found. "
                "Upgrade faster-whisper, and ensure ffmpeg is installed and on PATH."
            ) from exc
    return decode_audio(path, sampling_rate=voice_settings.sample_rate)


def transcribe_file(path: str, export_txt: bool = True) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    audio = decode_audio_file(str(source))
    stt = SpeechToText(voice_settings)
    result = stt.transcribe(audio)

    txt_path: str | None = None
    if export_txt:
        txt_file = source.with_suffix(".txt")
        txt_file.write_text(result.text, encoding="utf-8")
        txt_path = str(txt_file)
        logger.info("Exported transcript to '%s'", txt_path)

    logger.info(
        "Transcribed '%s' (language=%s, probability=%.2f)",
        path,
        result.detected_language,
        result.language_probability,
    )
    return {
        "text": result.text,
        "language": result.detected_language,
        "language_probability": result.language_probability,
        "txt_path": txt_path,
    }


class LocalWhisperTranscriber:
    """Adapter satisfying modules.crm_transcribe.ports.TranscriptionPort."""

    transcribe_file = staticmethod(transcribe_file)
