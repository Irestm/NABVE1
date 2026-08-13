from __future__ import annotations

import numpy as np

# webrtcvad only accepts 10/20/30ms frames; 30ms gives the most stable
# classification of the three at the cost of a little latency, which is
# irrelevant here since frames are only used to decide when to stop
# recording, not for real-time streaming.
FRAME_MS = 30


class SpeechActivityDetector:
    """Wraps webrtcvad.Vad to classify fixed-size frames of 16-bit-PCM-
    equivalent mono audio as speech/silence, replacing the raw RMS-energy
    threshold that used to decide when a user had finished talking (see
    core/voice/audio_io.py). Requires the `webrtcvad` package — installed
    via `webrtcvad-wheels` in requirements.txt for prebuilt wheels."""

    def __init__(self, sample_rate: int, aggressiveness: int = 2) -> None:
        import webrtcvad

        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(f"webrtcvad does not support sample_rate={sample_rate}")
        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        self.frame_samples = int(sample_rate * FRAME_MS / 1000)

    def is_speech(self, frame: np.ndarray) -> bool:
        """`frame` must be exactly `self.frame_samples` float32 samples in
        [-1, 1]. A frame of any other length (e.g. a short final read at
        stream end) is treated as silence rather than raising, since
        callers don't always control chunk boundaries exactly."""
        if frame.shape[0] != self.frame_samples:
            return False
        pcm16 = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16).tobytes()
        return bool(self._vad.is_speech(pcm16, self._sample_rate))
