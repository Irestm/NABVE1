from __future__ import annotations

import numpy as np

from core.voice.config import VoiceSettings
from core.voice.transcription import TranscriptionResult
from core.voice.whisper_engine import CPU_COMPUTE_TYPE, CPU_DEVICE, WhisperEngine


class ListeningSpeechToText:
    def __init__(self, settings: VoiceSettings, model_size: str | None = None) -> None:
        self._engine = WhisperEngine(
            model_size or settings.whisper_wake_model_size,
            CPU_DEVICE,
            CPU_COMPUTE_TYPE,
            block_torch_import=True,
        )

    @property
    def model_size(self) -> str:
        return self._engine.model_size

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        return self._engine.transcribe(audio, language)
