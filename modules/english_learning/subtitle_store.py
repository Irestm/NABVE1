from __future__ import annotations

import re
from pathlib import Path

from core.config import DATA_DIR

SUBTITLES_DIR: Path = DATA_DIR / "subtitles"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _folder_name(imdb_id: str | None, series_title: str) -> str:
    if imdb_id:
        return _UNSAFE.sub("_", imdb_id)
    slug = _UNSAFE.sub("_", series_title.strip().lower()).strip("_")
    return f"local_{slug or 'series'}"


def subtitle_path(imdb_id: str | None, series_title: str, season: int, episode: int, variant: str = "en") -> Path:
    return SUBTITLES_DIR / _folder_name(imdb_id, series_title) / f"S{season:02d}E{episode:02d}.{variant}.srt"


def cached(imdb_id: str | None, series_title: str, season: int, episode: int) -> Path | None:
    path = subtitle_path(imdb_id, series_title, season, episode)
    return path if path.exists() and path.stat().st_size > 0 else None


def save(imdb_id: str | None, series_title: str, season: int, episode: int, text: str, variant: str = "en") -> Path:
    path = subtitle_path(imdb_id, series_title, season, episode, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
