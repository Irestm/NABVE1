from __future__ import annotations

import sys
import threading
from types import ModuleType
from typing import Any

import numpy as np

from core.logger import get_logger
from core.voice.transcription import EMPTY_TRANSCRIPTION, TranscriptionResult

logger = get_logger(__name__)

CPU_DEVICE = "cpu"
CUDA_DEVICE = "cuda"
CPU_COMPUTE_TYPE = "int8"

_CUDA_LIBRARY_MARKERS: tuple[str, ...] = ("cublas", "cudnn", "libcuda", "cuda driver")
_IMPORT_LOCK = threading.Lock()


def import_faster_whisper(block_torch_import: bool) -> ModuleType:
    with _IMPORT_LOCK:
        if not block_torch_import or "torch" in sys.modules or "faster_whisper" in sys.modules:
            import faster_whisper

            return faster_whisper
        sys.modules["torch"] = None  # type: ignore[assignment]
        try:
            import faster_whisper

            return faster_whisper
        finally:
            if "torch" in sys.modules and sys.modules["torch"] is None:
                del sys.modules["torch"]


def import_torch() -> ModuleType:
    with _IMPORT_LOCK:
        import torch

        return torch


def is_cuda_library_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CUDA_LIBRARY_MARKERS)


class WhisperEngine:
    def __init__(
        self,
        model_size: str,
        device: str,
        compute_type: str,
        *,
        num_workers: int = 1,
        block_torch_import: bool = False,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type if device != CPU_DEVICE else CPU_COMPUTE_TYPE
        self._num_workers = num_workers
        self._block_torch_import = block_torch_import
        self._model: Any | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        return self._device

    @property
    def model_size(self) -> str:
        return self._model_size

    def load(self) -> None:
        self._get_model()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    faster_whisper = import_faster_whisper(self._block_torch_import)
                except ImportError as exc:
                    raise RuntimeError(
                        "faster-whisper is not installed. Install it with: pip install faster-whisper"
                    ) from exc
                self._model = faster_whisper.WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                    num_workers=self._num_workers,
                )
            return self._model

    def _fall_back_to_cpu(self, exc: BaseException) -> None:
        with self._lock:
            if self._device == CPU_DEVICE:
                return
            logger.warning(
                "faster-whisper couldn't use its CUDA libraries (%s); falling back to CPU for this model.",
                exc,
            )
            self._device = CPU_DEVICE
            self._compute_type = CPU_COMPUTE_TYPE
            self._model = None

    def _decode(self, audio: np.ndarray, language: str | None) -> TranscriptionResult:
        model = self._get_model()
        # `language`: pin decoding to a known language (e.g. from a UI toggle)
        # when given — skips Whisper's own language-ID pass entirely, which is
        # both faster and more accurate than decoding against a guess. None
        # falls back to autodetect, for when the caller has no hint.
        # beam_size=5: greedy decoding (beam_size=1) was the original default
        # for max speed, but combined with the "tiny" model it produced too
        # many real misrecognitions in everyday use (see VoiceSettings.
        # whisper_model_size) — a proper beam search meaningfully improves
        # accuracy for the cost of a short single-utterance decode, which
        # isn't on any tight latency budget here.
        # vad_filter=True: Whisper is notorious for hallucinating stock
        # phrases (e.g. video subtitle credits — it was trained on a lot of
        # captioned video) when fed silence or non-speech noise instead of
        # returning empty text. Silero VAD strips those segments out before
        # they ever reach the decoder, rather than trying to filter
        # hallucinated text after the fact.
        # condition_on_previous_text=False: without it, one hallucinated
        # segment biases the decoding of the next one within the same clip,
        # compounding the problem instead of the two being decoded independently.
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return TranscriptionResult(
            text=text,
            detected_language=info.language,
            language_probability=info.language_probability,
        )

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        if audio.size == 0:
            return EMPTY_TRANSCRIPTION
        try:
            return self._decode(audio, language)
        except RuntimeError as exc:
            if self._device == CPU_DEVICE or not is_cuda_library_error(exc):
                raise
            self._fall_back_to_cpu(exc)
            return self._decode(audio, language)
