from __future__ import annotations

import numpy as np

from core.voice.config import VoiceSettings
from core.voice.transcription import TranscriptionResult
from core.voice.whisper_engine import CPU_DEVICE, CUDA_DEVICE, WhisperEngine

__all__ = ["SpeechToText", "TranscriptionResult"]


class SpeechToText:
    def __init__(self, settings: VoiceSettings, model_size: str | None = None) -> None:
        self._settings = settings
        self._model_size = model_size or settings.whisper_model_size
        device = settings.whisper_device if settings.whisper_device in (CPU_DEVICE, CUDA_DEVICE) else CPU_DEVICE
        self._engine = WhisperEngine(
            self._model_size,
            device,
            settings.whisper_compute_type,
            block_torch_import=True,
        )

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        return self._engine.transcribe(audio, language)
