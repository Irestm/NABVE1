from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class _Line:
    speaker: str
    text: str


@dataclass
class DiscussionSession:
    """In-memory only. The live transcript of a conversation is sensitive —
    it is never written to disk unless the user explicitly turns that on
    (not implemented yet), and it is dropped entirely on deactivate()."""

    _active: bool = False
    _lines: list[_Line] = field(default_factory=list)
    # Index into _lines up to which Jarvis has already given an opinion, so
    # transcript_since_last_opinion() returns only the new part.
    _opinion_mark: int = 0
    # 0-2 running pitch centroids for speaker_diarization.
    pitch_centroids: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        with self._lock:
            self._active = True
            self._lines.clear()
            self._opinion_mark = 0
            self.pitch_centroids.clear()

    def deactivate(self) -> None:
        with self._lock:
            self._active = False
            self._lines.clear()
            self._opinion_mark = 0
            self.pitch_centroids.clear()

    def add_line(self, speaker: str, text: str) -> None:
        with self._lock:
            self._lines.append(_Line(speaker=speaker, text=text.strip()))

    def transcript_since_last_opinion(self) -> str:
        with self._lock:
            recent = self._lines[self._opinion_mark :]
        return "\n".join(f"{line.speaker}: {line.text}" for line in recent)

    def full_transcript(self) -> str:
        with self._lock:
            return "\n".join(f"{line.speaker}: {line.text}" for line in self._lines)

    def mark_opinion_given(self) -> None:
        with self._lock:
            self._opinion_mark = len(self._lines)

    def line_count(self) -> int:
        with self._lock:
            return len(self._lines)


session = DiscussionSession()
