from __future__ import annotations

from typing import Any

import httpx

from modules.english_learning.srt_parser import cues_to_srt, parse_vtt

_ENGLISH_CODES: tuple[str, ...] = ("en", "en-US", "en-GB", "en-orig")
_TIMEOUT_SECONDS = 20.0


class YoutubeSubtitlesError(RuntimeError):
    pass


def _pick_track(tracks: dict[str, list[dict[str, Any]]]) -> str | None:
    for code in (*_ENGLISH_CODES, *sorted(code for code in tracks if code.startswith("en"))):
        for entry in tracks.get(code, []):
            if entry.get("ext") == "vtt" and entry.get("url"):
                return str(entry["url"])
    return None


def _extract_info(url: str) -> dict[str, Any]:
    import yt_dlp

    options = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YoutubeSubtitlesError(f"YouTube: не удалось получить данные ролика ({exc})") from exc
    return dict(info or {})


def fetch_english_srt(url: str) -> tuple[str, str | None]:
    info = _extract_info(url)
    track_url = _pick_track(info.get("subtitles") or {}) or _pick_track(info.get("automatic_captions") or {})
    if track_url is None:
        raise YoutubeSubtitlesError("У ролика нет английских субтитров")
    try:
        response = httpx.get(track_url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise YoutubeSubtitlesError(f"Не удалось скачать субтитры YouTube: {exc}") from exc
    return cues_to_srt(parse_vtt(response.text)), info.get("title")
