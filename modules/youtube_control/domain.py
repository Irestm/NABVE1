from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoResult:
    video_id: str
    title: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class QuotaStatus:
    units_used: int
    daily_limit: int
    remaining_searches: int
    near_limit: bool
    exhausted: bool
