from __future__ import annotations

from typing import Any

from modules.ai_bridge.providers.base import AIResult, ChatMessage
from modules.ai_bridge.providers.router import ProviderRouter, get_router
from modules.english_learning.domain import SubtitleCue
from modules.english_learning.link_parser import LinkGuess

LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["series", "movie", "unknown"]},
        "series_title": {"type": ["string", "null"]},
        "year": {"type": ["integer", "null"]},
        "season": {"type": ["integer", "null"]},
        "episode": {"type": ["integer", "null"]},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "series_title", "year", "season", "episode", "alternatives"],
    "additionalProperties": False,
}

GUESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "minute": {"type": "integer"}},
                "required": ["text", "minute"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

_GUESS_MAX_TOKENS = 4000
_LINK_MAX_TOKENS = 300


async def _complete(
    router: ProviderRouter | None, messages: list[ChatMessage], schema: dict[str, Any], max_tokens: int
) -> AIResult:
    return await (router or get_router()).complete(messages, json_schema=schema, max_tokens=max_tokens)


async def resolve_link(guess: LinkGuess, router: ProviderRouter | None = None) -> tuple[LinkGuess, list[str]]:
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": (
                "You identify TV series episodes and movies from web links. Decide kind: 'series' for a TV "
                "episode, 'movie' for a feature film, 'unknown' if unsure. Return the official English title "
                "(as on TMDB/IMDb) in series_title, the release year for movies, season and episode numbers for "
                "series. Use null for anything you cannot determine. List other plausible titles in alternatives."
            ),
        },
        {"role": "user", "content": f"URL: {guess.url}\nPage title: {guess.page_title or '-'}"},
    ]
    result = await _complete(router, messages, LINK_SCHEMA, _LINK_MAX_TOKENS)
    data = result.parsed_json if isinstance(result.parsed_json, dict) else {}
    title = data.get("series_title")
    season = data.get("season")
    episode = data.get("episode")
    kind = data.get("kind")
    year = data.get("year")
    alternatives = [str(item) for item in data.get("alternatives", []) if isinstance(item, str) and item.strip()]
    return (
        LinkGuess(
            url=guess.url,
            series_title=guess.series_title or (str(title) if isinstance(title, str) and title.strip() else None),
            season=guess.season if guess.season is not None else (season if isinstance(season, int) else None),
            episode=guess.episode if guess.episode is not None else (episode if isinstance(episode, int) else None),
            youtube_id=guess.youtube_id,
            page_title=guess.page_title,
            kind=guess.kind or (kind if kind in ("series", "movie") else None),
            year=guess.year if guess.year is not None else (year if isinstance(year, int) else None),
        ),
        alternatives,
    )


async def guess_dialogue(
    series_title: str,
    season: int | None,
    episode: int | None,
    episode_title: str | None,
    router: ProviderRouter | None = None,
) -> list[SubtitleCue]:
    if season is None or episode is None:
        label = f"Movie: {series_title}" + (f" ({episode_title})" if episode_title else "")
    else:
        label = f"{series_title} S{season:02d}E{episode:02d}" + (f" “{episode_title}”" if episode_title else "")
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": (
                "You help an English learner. Subtitles are unavailable. From your knowledge of "
                "the episode or movie, write 40-80 short English dialogue lines (max 15 words each) that plausibly occur in "
                "it, in story order, with the approximate minute. Prefer everyday vocabulary the characters "
                "really use. Do not invent plot facts you are unsure about; keep lines generic if needed."
            ),
        },
        {"role": "user", "content": label},
    ]
    result = await _complete(router, messages, GUESS_SCHEMA, _GUESS_MAX_TOKENS)
    data = result.parsed_json if isinstance(result.parsed_json, dict) else {}
    cues: list[SubtitleCue] = []
    for item in data.get("lines", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        minute = item.get("minute")
        if not text:
            continue
        start = max(0, int(minute) if isinstance(minute, int) else 0) * 60_000 + len(cues) * 1000
        cues.append(SubtitleCue(index=len(cues) + 1, start_ms=start, end_ms=start + 3000, text=text))
    return cues
