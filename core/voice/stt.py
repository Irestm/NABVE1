from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.logger import get_logger
from core.voice.config import VoiceSettings

logger = get_logger(__name__)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    detected_language: str | None
    language_probability: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
        }


class SpeechToText:
    def __init__(self, settings: VoiceSettings, model_size: str | None = None) -> None:
        self._settings = settings
        self._model_size = model_size or settings.whisper_model_size
        self._model: Any | None = None
        # Mutable copies of the configured device/compute type — torch.cuda.
        # is_available() (see VoiceSettings._detect_whisper_device) only
        # proves the driver + PyTorch's own bundled CUDA runtime work; it
        # says nothing about whether faster-whisper's separate ctranslate2
        # backend can load the system-wide cuBLAS/cuDNN libraries it needs.
        # That failure only surfaces on the first real transcribe() call
        # (ctranslate2 loads CUDA lazily), not at model construction — see
        # transcribe()'s fallback below, which downgrades these to CPU and
        # rebuilds the model once, permanently, for the rest of this
        # process's life instead of failing every single call.
        self._device = settings.whisper_device
        self._compute_type = settings.whisper_compute_type

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed. Install it with: pip install faster-whisper"
                ) from exc
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        if audio.size == 0:
            return TranscriptionResult(text="", detected_language=None, language_probability=0.0)

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
        try:
            segments, info = model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except RuntimeError as exc:
            if self._device != "cuda" or "cublas" not in str(exc).lower():
                raise
            logger.warning(
                "faster-whisper couldn't load its CUDA libraries (%s) despite torch.cuda.is_available() — "
                "falling back to CPU for the rest of this process.",
                exc,
            )
            self._device = "cpu"
            self._compute_type = "int8"
            self._model = None
            model = self._get_model()
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
