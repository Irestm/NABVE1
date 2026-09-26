from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from core.logger import get_logger
from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning import ai_assist, credentials, link_parser, service_layer, subtitle_store, youtube_subs
from modules.english_learning.domain import EpisodeSource, SubtitleCue
from modules.english_learning.link_parser import LinkGuess
from modules.english_learning.opensubtitles import OpenSubtitlesClient, OpenSubtitlesError
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.srt_parser import cues_to_srt
from modules.english_learning.tmdb import TmdbClient, TmdbError, TmdbShow

logger = get_logger(__name__)

NeedKind = Literal["details", "series", "subtitles"]
_OPTIONS_LIMIT = 5
_DOMINANT_POPULARITY_RATIO = 2.0


@dataclass(frozen=True)
class LinkImportRequest:
    url: str
    series_title: str | None = None
    season: int | None = None
    episode: int | None = None
    tmdb_id: int | None = None
    allow_ai_guess: bool = False


@dataclass(frozen=True)
class ShowOption:
    tmdb_id: int
    name: str
    year: int | None


@dataclass(frozen=True)
class NeedsInput:
    kind: NeedKind
    message: str
    guess: LinkGuess
    missing: list[str] = field(default_factory=list)
    options: list[ShowOption] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedShow:
    title: str
    tmdb_id: int | None
    imdb_id: str | None
    episode_title: str | None


@dataclass
class LinkImportDeps:
    fetch_page_title: Callable[[str], str | None] = link_parser.fetch_page_title
    resolve_link: Callable[[LinkGuess], Awaitable[tuple[LinkGuess, list[str]]]] = ai_assist.resolve_link
    guess_dialogue: Callable[[str, int, int, str | None], Awaitable[list[SubtitleCue]]] = ai_assist.guess_dialogue
    tmdb_factory: Callable[[], TmdbClient | None] = lambda: (
        TmdbClient(key) if (key := credentials.tmdb_key()) else None
    )
    opensubtitles_factory: Callable[[], OpenSubtitlesClient | None] = lambda: (
        OpenSubtitlesClient(creds) if (creds := credentials.opensubtitles()) else None
    )
    fetch_youtube: Callable[[str], tuple[str, str | None]] = youtube_subs.fetch_english_srt
    import_subtitles: Callable[..., ImportResult] = service_layer.import_subtitles
    stored_source: Callable[[str, str | None, int, int], EpisodeSource | None] = service_layer.stored_source


def _missing_fields(guess: LinkGuess) -> list[str]:
    missing: list[str] = []
    if not guess.series_title:
        missing.append("series_title")
    if guess.season is None:
        missing.append("season")
    if guess.episode is None:
        missing.append("episode")
    return missing


def _pick_show(shows: list[TmdbShow], title: str) -> TmdbShow | None:
    if not shows:
        return None
    exact = [show for show in shows if title.lower() in (show.name.lower(), show.original_name.lower())]
    if len(exact) == 1:
        return exact[0]
    ranked = sorted(exact or shows, key=lambda show: show.popularity, reverse=True)
    if len(ranked) == 1 or ranked[0].popularity >= _DOMINANT_POPULARITY_RATIO * max(ranked[1].popularity, 0.001):
        return ranked[0]
    return None


def _resolve_show(
    tmdb: TmdbClient, request: LinkImportRequest, guess: LinkGuess
) -> ResolvedShow | list[ShowOption]:
    assert guess.series_title is not None and guess.season is not None and guess.episode is not None
    if request.tmdb_id is not None:
        tmdb_id = request.tmdb_id
        title = tmdb.english_name(tmdb_id) or guess.series_title
    else:
        shows = tmdb.search_tv(guess.series_title)
        show = _pick_show(shows, guess.series_title)
        if show is None:
            return [ShowOption(item.tmdb_id, item.name, item.year) for item in shows[:_OPTIONS_LIMIT]]
        tmdb_id = show.tmdb_id
        title = tmdb.english_name(tmdb_id) or show.name
    return ResolvedShow(
        title=title,
        tmdb_id=tmdb_id,
        imdb_id=tmdb.imdb_id(tmdb_id),
        episode_title=tmdb.episode_title(tmdb_id, guess.season, guess.episode),
    )


async def import_from_link(request: LinkImportRequest, deps: LinkImportDeps | None = None) -> ImportResult | NeedsInput:
    deps = deps or LinkImportDeps()
    page_title = await asyncio.to_thread(deps.fetch_page_title, request.url)
    guess = link_parser.merge(
        link_parser.parse_link(request.url, page_title),
        series_title=request.series_title,
        season=request.season,
        episode=request.episode,
    )
    alternatives: list[str] = []
    if not guess.complete:
        try:
            guess, alternatives = await deps.resolve_link(guess)
        except AllProvidersFailed:
            logger.warning("AI could not resolve link %s; asking the user", request.url)

    missing = _missing_fields(guess)
    if missing:
        return NeedsInput(
            kind="details",
            message="Не удалось определить сериал, сезон или серию — уточните.",
            guess=guess,
            missing=missing,
            alternatives=alternatives,
        )
    assert guess.series_title is not None and guess.season is not None and guess.episode is not None

    problems: list[str] = []
    show = ResolvedShow(title=guess.series_title, tmdb_id=None, imdb_id=None, episode_title=None)
    tmdb = deps.tmdb_factory()
    if tmdb is None:
        problems.append("TMDB: ключ не задан — сериал не уточнён, OpenSubtitles недоступен")
    else:
        try:
            resolved = await asyncio.to_thread(_resolve_show, tmdb, request, guess)
        except TmdbError as exc:
            problems.append(f"TMDB: {exc}")
        else:
            if isinstance(resolved, list):
                return NeedsInput(
                    kind="series",
                    message="Найдено несколько сериалов — выберите нужный." if resolved else "TMDB не нашёл такой сериал.",
                    guess=guess,
                    options=resolved,
                    alternatives=alternatives,
                )
            show = resolved

    srt_text: str | None = None
    source: EpisodeSource = "manual"
    cached = subtitle_store.cached(show.imdb_id, show.title, guess.season, guess.episode)
    if cached is not None:
        srt_text = cached.read_text(encoding="utf-8")
        known = await asyncio.to_thread(deps.stored_source, show.title, show.imdb_id, guess.season, guess.episode)
        source = known if known is not None and known != "ai_guess" else "manual"

    if srt_text is None and guess.is_youtube:
        try:
            srt_text, _video_title = await asyncio.to_thread(deps.fetch_youtube, request.url)
            source = "youtube"
        except youtube_subs.YoutubeSubtitlesError as exc:
            problems.append(str(exc))

    if srt_text is None:
        client = deps.opensubtitles_factory()
        if client is None:
            problems.append("OpenSubtitles: ключ API не задан")
        elif show.imdb_id is None:
            problems.append("OpenSubtitles: нет IMDb ID (нужен TMDB)")
        else:
            try:
                srt_text = await asyncio.to_thread(client.fetch_episode, show.imdb_id, guess.season, guess.episode)
            except (OpenSubtitlesError, ValueError) as exc:
                problems.append(f"OpenSubtitles: {exc}")
            else:
                if srt_text is None:
                    problems.append("OpenSubtitles: английских субтитров для этой серии нет")
                source = "opensubtitles"

    if srt_text is None:
        if not request.allow_ai_guess:
            return NeedsInput(
                kind="subtitles",
                message="Субтитры не найдены автоматически — загрузите .srt вручную или разрешите примерный вариант от ИИ.",
                guess=link_parser.merge(guess, series_title=show.title, season=None, episode=None),
                problems=problems,
            )
        try:
            cues = await deps.guess_dialogue(show.title, guess.season, guess.episode, show.episode_title)
        except AllProvidersFailed as exc:
            problems.append(f"ИИ: {exc}")
            cues = []
        if not cues:
            return NeedsInput(
                kind="subtitles",
                message="Даже ИИ не смог подобрать реплики — загрузите .srt вручную.",
                guess=guess,
                problems=problems,
            )
        srt_text = cues_to_srt(cues)
        source = "ai_guess"

    return await asyncio.to_thread(
        deps.import_subtitles,
        series_title=show.title,
        season=guess.season,
        episode=guess.episode,
        srt_text=srt_text,
        source=source,
        imdb_id=show.imdb_id,
        tmdb_id=show.tmdb_id,
        episode_title=show.episode_title,
    )
