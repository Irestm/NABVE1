from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackResult:
    uri: str
    name: str
    artist: str


@dataclass(frozen=True)
class PlaybackState:
    track_name: str
    artist: str
    is_playing: bool
