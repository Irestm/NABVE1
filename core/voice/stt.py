from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.voice.config import VoiceSettings


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
                device=self._settings.whisper_device,
                compute_type=self._settings.whisper_compute_type,
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
