from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modules.english_learning.domain import SubtitleCue

DEFAULT_PART_MINUTES = 20
MIN_PART_MINUTES = 10
MAX_PART_MINUTES = 40
SEARCH_WINDOW_SHARE = 0.25
MIN_LAST_PART_SHARE = 0.34


@dataclass(frozen=True)
class PartSpan:
    number: int
    start_ms: int
    end_ms: int


def clamp_minutes(minutes: int) -> int:
    return max(MIN_PART_MINUTES, min(MAX_PART_MINUTES, minutes))


def _boundary_near(cues: Sequence[SubtitleCue], target_ms: int, window_ms: int, after_ms: int) -> int | None:
    best: tuple[int, int, int] | None = None
    for previous, following in zip(cues, cues[1:]):
        if following.start_ms <= after_ms:
            continue
        gap = following.start_ms - previous.end_ms
        distance = abs(following.start_ms - target_ms)
        if distance > window_ms:
            continue
        key = (distance - min(gap, window_ms) // 4, distance, following.start_ms)
        if best is None or key < best:
            best = key
    return best[2] if best is not None else None


def split_parts(cues: Sequence[SubtitleCue], part_minutes: int = DEFAULT_PART_MINUTES) -> list[PartSpan]:
    if not cues:
        return []
    part_ms = clamp_minutes(part_minutes) * 60_000
    window_ms = int(part_ms * SEARCH_WINDOW_SHARE)
    total_end = max(cue.end_ms for cue in cues)
    boundaries: list[int] = []
    last = 0
    while total_end - last > part_ms * (1 + MIN_LAST_PART_SHARE):
        target = last + part_ms
        boundary = _boundary_near(cues, target, window_ms, last)
        if boundary is None:
            boundary = next((cue.start_ms for cue in cues if cue.start_ms >= target), None)
        if boundary is None or boundary <= last:
            break
        boundaries.append(boundary)
        last = boundary
    starts = [0, *boundaries]
    ends = [*boundaries, total_end]
    return [PartSpan(number=i + 1, start_ms=start, end_ms=end) for i, (start, end) in enumerate(zip(starts, ends))]
