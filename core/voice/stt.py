from __future__ import annotations

from typing import Any

import numpy as np

from core.gpu_worker.client import GpuWorkerClient, get_gpu_worker_client
from core.voice.config import VoiceSettings
from core.voice.transcription import EMPTY_TRANSCRIPTION, TranscriptionResult

__all__ = ["SpeechToText", "TranscriptionResult"]

_LOAD_TIMEOUT_SECONDS = 600.0
_TRANSCRIBE_BASE_TIMEOUT_SECONDS = 600.0
_TRANSCRIBE_SECONDS_PER_AUDIO_SECOND = 3.0


class SpeechToText:
    def __init__(
        self,
        settings: VoiceSettings,
        model_size: str | None = None,
        client: GpuWorkerClient | None = None,
    ) -> None:
        self._settings = settings
        self._model_size = model_size or settings.whisper_model_size
        self._client = client

    def _worker(self) -> GpuWorkerClient:
        return self._client or get_gpu_worker_client()

    def _model_args(self) -> dict[str, Any]:
        return {
            "model_size": self._model_size,
            "device": self._settings.whisper_device,
            "compute_type": self._settings.whisper_compute_type,
        }

    def prewarm(self) -> None:
        self._worker().call_in_background("stt.load", self._model_args(), _LOAD_TIMEOUT_SECONDS)

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        if audio.size == 0:
            return EMPTY_TRANSCRIPTION
        samples = np.ascontiguousarray(audio, dtype=np.float32)
        audio_seconds = samples.shape[0] / self._settings.sample_rate
        timeout = _TRANSCRIBE_BASE_TIMEOUT_SECONDS + audio_seconds * _TRANSCRIBE_SECONDS_PER_AUDIO_SECOND
        raw = self._worker().call(
            "stt.transcribe",
            {**self._model_args(), "audio": samples, "language": language},
            timeout,
        )
        return TranscriptionResult.from_dict(raw)
