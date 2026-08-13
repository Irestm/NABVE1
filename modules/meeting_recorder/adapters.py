from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from core.ai_adapter_chain import local_first_chain
from core.logger import get_logger
from core.voice.ai_router import is_degenerate_answer
from core.voice.config import voice_settings
from core.voice.stt import SpeechToText
from modules.crm_transcribe import transcriber as crm_transcriber
from modules.meeting_recorder import audio_processing
from modules.meeting_recorder.domain import TRANSCRIPT_CHUNK_SECONDS

logger = get_logger(__name__)

_SUMMARY_PROMPT_TEMPLATE = (
    "Ниже — расшифровка звонка/встречи. Составь краткое связное саммари на русском языке: "
    "основные обсуждённые темы и, если они прозвучали в разговоре, принятые решения и "
    "договорённости о дальнейших действиях. Пиши только то, что реально есть в расшифровке, "
    "ничего не придумывай. Если расшифровка слишком короткая или бессвязная, чтобы выделить "
    "из неё что-то осмысленное — так и скажи одной фразой.\n\n"
    "Расшифровка:\n{transcript}"
)


class LocalAudioConverter:
    """Adapter satisfying modules.meeting_recorder.ports.AudioConverterPort
    over the real ffmpeg/ffprobe-backed implementation."""

    def convert_to_ogg(self, raw_path: Path, output_path: Path) -> None:
        audio_processing.convert_to_ogg(raw_path, output_path)

    def probe_duration_seconds(self, path: Path) -> float:
        return audio_processing.probe_duration_seconds(path)


class LocalWhisperMeetingTranscriber:
    """Adapter satisfying modules.meeting_recorder.ports.TranscriberPort —
    reuses core.voice.stt.SpeechToText (the same faster-whisper wrapper
    already used by the live voice pipeline and modules.crm_transcribe)
    rather than loading a second model. Slices the decoded audio into fixed
    windows so a near-2h30m recording reports incremental progress instead
    of blocking behind one opaque call."""

    def __init__(self, chunk_seconds: int = TRANSCRIPT_CHUNK_SECONDS) -> None:
        self._chunk_seconds = chunk_seconds
        self._stt = SpeechToText(voice_settings)

    def transcribe(self, audio_path: Path, *, on_progress: Callable[[float], None]) -> str:
        # Reuses crm_transcribe's decode helper rather than duplicating the
        # "faster-whisper's ffmpeg-backed decode_audio, tried under both its
        # old and new import paths" fallback logic a third time in this
        # codebase.
        audio = crm_transcriber.decode_audio_file(str(audio_path))
        chunk_samples = self._chunk_seconds * voice_settings.sample_rate
        total_samples = audio.shape[0]
        if total_samples == 0:
            on_progress(1.0)
            return ""

        chunk_bounds = list(range(0, total_samples, chunk_samples))
        pieces: list[str] = []
        for index, start in enumerate(chunk_bounds):
            end = min(start + chunk_samples, total_samples)
            chunk_audio = np.ascontiguousarray(audio[start:end])
            # One bad window (a transient STT error, a corrupted/silent
            # stretch) must not throw away every chunk already transcribed
            # before it — for a near-2h30m/15-chunk recording, letting this
            # propagate used to fail transcript_status for the whole
            # recording over a single 10-minute window. Skip just this
            # chunk's text and keep going instead.
            try:
                result = self._stt.transcribe(chunk_audio)
            except Exception:
                logger.exception(
                    "Transcription failed for chunk %d/%d of %s; continuing with the rest",
                    index + 1,
                    len(chunk_bounds),
                    audio_path,
                )
            else:
                if result.text:
                    pieces.append(result.text)
            on_progress((index + 1) / len(chunk_bounds))

        return " ".join(pieces).strip()


class LocalFirstSummarizer:
    """Adapter satisfying modules.meeting_recorder.ports.SummarizerPort —
    reuses the same local-model-first / ai_bridge-fallback adapter chain
    core.voice.ai_router uses for free-text answers (core.ai_adapter_chain.
    local_first_chain), instead of standing up a separate LLM client just
    for this module."""

    async def summarize(self, transcript_text: str) -> str:
        prompt = _SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript_text)
        last_error: Exception | None = None
        for adapter in local_first_chain():
            try:
                answer = await adapter.send_prompt(prompt, fast_mode=False)
                if is_degenerate_answer(answer):
                    logger.warning(
                        "Summarizer adapter '%s' returned a degenerate answer, trying next",
                        adapter.name,
                    )
                    continue
                return answer
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Summarizer adapter '%s' failed, trying next: %s", adapter.name, exc, exc_info=exc
                )
        raise RuntimeError("All summary adapters failed") from last_error
