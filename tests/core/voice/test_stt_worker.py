from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from core.voice.config import VoiceSettings
from core.voice.silero_tts import SileroVoice
from core.voice.stt import SpeechToText, TranscriptionResult


class _FakeWorkerClient:
    def __init__(self, result: Any = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], float]] = []
        self.background: list[tuple[str, dict[str, Any]]] = []
        self._result = result

    def call(self, op: str, args: dict[str, Any], timeout: float) -> Any:
        self.calls.append((op, args, timeout))
        return self._result

    def call_in_background(self, op: str, args: dict[str, Any], timeout: float) -> None:
        self.background.append((op, args))


def test_command_transcription_goes_to_the_worker_with_the_command_model() -> None:
    settings = VoiceSettings()
    client = _FakeWorkerClient({"text": "привет", "detected_language": "ru", "language_probability": 0.9})
    stt = SpeechToText(settings, client=client)  # type: ignore[arg-type]
    audio = np.ones(settings.sample_rate * 2, dtype=np.float64)

    result = stt.transcribe(audio, "ru")

    assert result == TranscriptionResult(text="привет", detected_language="ru", language_probability=0.9)
    op, args, timeout = client.calls[0]
    assert op == "stt.transcribe"
    assert args["model_size"] == settings.whisper_model_size
    assert args["device"] == settings.whisper_device
    assert args["language"] == "ru"
    assert args["audio"].dtype == np.float32
    assert timeout > 2.0


def test_empty_audio_never_reaches_the_worker() -> None:
    client = _FakeWorkerClient()
    stt = SpeechToText(VoiceSettings(), client=client)  # type: ignore[arg-type]

    result = stt.transcribe(np.zeros(0, dtype=np.float32))

    assert result.text == ""
    assert client.calls == []


def test_prewarm_loads_the_model_in_the_background() -> None:
    client = _FakeWorkerClient()
    stt = SpeechToText(VoiceSettings(), model_size="base", client=client)  # type: ignore[arg-type]

    stt.prewarm()

    assert client.background[0][0] == "stt.load"
    assert client.background[0][1]["model_size"] == "base"


def test_default_whisper_device_is_left_to_the_worker() -> None:
    assert VoiceSettings().whisper_device in ("auto", "cpu", "cuda")


def test_silero_synthesis_goes_to_the_worker() -> None:
    samples = np.zeros(10, dtype=np.float32)
    client = _FakeWorkerClient((samples, 48000))
    voice = SileroVoice(Path("/models/silero.pt"), speaker="baya", client=client)  # type: ignore[arg-type]

    audio, sample_rate = voice.synthesize("привет")

    assert sample_rate == 48000
    assert np.array_equal(audio, samples)
    op, args, _timeout = client.calls[0]
    assert op == "tts.silero"
    assert args == {"model_path": "/models/silero.pt", "text": "привет", "speaker": "baya", "sample_rate": 48000}
