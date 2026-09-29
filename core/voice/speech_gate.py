from __future__ import annotations

import math

import numpy as np

from core.voice.config import VoiceSettings
from core.voice.vad import FRAME_MS

MIN_VOICED_FRAMES = 3


class SpeechGate:
    def __init__(
        self,
        sample_rate: int,
        aggressiveness: int,
        min_voiced_ratio: float,
        min_voiced_frames: int = MIN_VOICED_FRAMES,
    ) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        self._frame_samples = int(sample_rate * FRAME_MS / 1000)
        self._min_voiced_ratio = min_voiced_ratio
        self._min_voiced_frames = min_voiced_frames
        self._scratch = np.empty(0, dtype=np.float32)
        self._pcm = np.empty(0, dtype=np.int16)

    @classmethod
    def from_settings(cls, settings: VoiceSettings) -> SpeechGate:
        return cls(settings.sample_rate, settings.vad_aggressiveness, settings.wake_gate_min_voiced_ratio)

    @property
    def enabled(self) -> bool:
        return self._min_voiced_ratio > 0

    def required_voiced_frames(self, frame_count: int) -> int:
        return max(self._min_voiced_frames, math.ceil(frame_count * self._min_voiced_ratio))

    def voiced_frames(self, window: np.ndarray) -> int:
        frames = self._to_pcm_frames(window)
        return sum(1 for frame in frames if self._vad.is_speech(frame, self._sample_rate))

    def should_transcribe(self, window: np.ndarray) -> bool:
        if window.size == 0:
            return False
        if not self.enabled:
            return True
        frames = self._to_pcm_frames(window)
        required = self.required_voiced_frames(len(frames))
        voiced = 0
        for index, frame in enumerate(frames):
            if self._vad.is_speech(frame, self._sample_rate):
                voiced += 1
                if voiced >= required:
                    return True
            if voiced + (len(frames) - index - 1) < required:
                return False
        return False

    def _to_pcm_frames(self, window: np.ndarray) -> list[memoryview]:
        frame_count = window.shape[0] // self._frame_samples
        usable = frame_count * self._frame_samples
        if usable == 0:
            return []
        if self._scratch.shape[0] < usable:
            self._scratch = np.empty(usable, dtype=np.float32)
            self._pcm = np.empty(usable, dtype=np.int16)
        scratch = self._scratch[:usable]
        pcm = self._pcm[:usable]
        np.multiply(window[:usable], 32768.0, out=scratch)
        np.clip(scratch, -32768.0, 32767.0, out=scratch)
        np.copyto(pcm, scratch, casting="unsafe")
        raw = memoryview(pcm).cast("B")
        frame_bytes = self._frame_samples * pcm.itemsize
        return [raw[index * frame_bytes : (index + 1) * frame_bytes] for index in range(frame_count)]
