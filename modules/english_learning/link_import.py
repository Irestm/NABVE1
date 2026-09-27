from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from core.logger import get_logger
from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning import ai_assist, credentials, link_parser, service_layer, subtitle_store, youtube_subs
from modules.english_learning.domain import EpisodeSource, SubtitleCue
from modules.english_learning.link_parser import LinkGuess
from modules.english_learning.movie_parts import DEFAULT_PART_MINUTES
from modules.english_learning.opensubtitles import OpenSubtitlesClient, OpenSubtitlesError
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.srt_parser import cues_to_srt
from modules.english_learning.tmdb import TmdbClient, TmdbError, TmdbMovie, TmdbShow, poster_url

logger = get_logger(__name__)

NeedKind = Literal["details", "series", "title", "subtitles"]
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
    kind: str | None = None
    year: int | None = None
    split_movie: bool = True
    part_minutes: int = DEFAULT_PART_MINUTES


@dataclass(frozen=True)
class ShowOption:
    tmdb_id: int
    name: str
    year: int | None
    kind: str = "series"
    poster_url: str | None = None


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


@dataclass(frozen=True)
class ResolvedMovie:
    title: str
    year: int | None
    tmdb_id: int | None
    imdb_id: str | None
    runtime_minutes: int | None


@dataclass
class LinkImportDeps:
    fetch_page_title: Callable[[str], str | None] = link_parser.fetch_page_title
    resolve_link: Callable[[LinkGuess], Awaitable[tuple[LinkGuess, list[str]]]] = ai_assist.resolve_link
    guess_dialogue: Callable[..., Awaitable[list[SubtitleCue]]] = ai_assist.guess_dialogue
    tmdb_factory: Callable[[], TmdbClient | None] = lambda: (
        TmdbClient(key) if (key := credentials.tmdb_key()) else None
    )
    opensubtitles_factory: Callable[[], OpenSubtitlesClient | None] = lambda: (
        OpenSubtitlesClient(creds) if (creds := credentials.opensubtitles()) else None
    )
    fetch_youtube: Callable[[str], tuple[str, str | None]] = youtube_subs.fetch_english_srt
    import_subtitles: Callable[..., ImportResult] = service_layer.import_subtitles
    import_movie: Callable[..., ImportResult] = service_layer.import_movie
    stored_source: Callable[[str, str | None, int, int], EpisodeSource | None] = service_layer.stored_source
    stored_movie_source: Callable[[str, str | None], EpisodeSource | None] = service_layer.stored_movie_source


def _missing_fields(guess: LinkGuess) -> list[str]:
    missing: list[str] = []
    if not guess.series_title:
        missing.append("series_title")
    if guess.kind == "movie":
        return missing
    if guess.season is None:
        missing.append("season")
    if guess.episode is None:
        missing.append("episode")
    return missing


def _exact(names: tuple[str, str], title: str) -> bool:
    return title.lower() in (names[0].lower(), names[1].lower())


def _pick_show(shows: list[TmdbShow], title: str) -> TmdbShow | None:
    if not shows:
        return None
    exact = [show for show in shows if _exact((show.name, show.original_name), title)]
    if len(exact) == 1:
        return exact[0]
    ranked = sorted(exact or shows, key=lambda show: show.popularity, reverse=True)
    if len(ranked) == 1 or ranked[0].popularity >= _DOMINANT_POPULARITY_RATIO * max(ranked[1].popularity, 0.001):
        return ranked[0]
    return None


def _pick_movie(movies: list[TmdbMovie], title: str, year: int | None) -> TmdbMovie | None:
    if not movies:
        return None
    exact = [movie for movie in movies if _exact((movie.title, movie.original_title), title)]
    if year is not None:
        dated = [movie for movie in (exact or movies) if movie.year == year]
        if len(dated) == 1:
            return dated[0]
        if dated:
            exact = dated
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    ranked = sorted(movies, key=lambda movie: movie.popularity, reverse=True)
    if len(ranked) == 1 or ranked[0].popularity >= _DOMINANT_POPULARITY_RATIO * max(ranked[1].popularity, 0.001):
        return ranked[0]
    return None


def _show_options(shows: list[TmdbShow]) -> list[ShowOption]:
    return [
        ShowOption(item.tmdb_id, item.name, item.year, "series", poster_url(item.poster_path))
        for item in shows[:_OPTIONS_LIMIT]
    ]


def _movie_options(movies: list[TmdbMovie]) -> list[ShowOption]:
    return [
        ShowOption(item.tmdb_id, item.title, item.year, "movie", poster_url(item.poster_path))
        for item in movies[:_OPTIONS_LIMIT]
    ]


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
            return _show_options(shows)
        tmdb_id = show.tmdb_id
        title = tmdb.english_name(tmdb_id) or show.name
    return ResolvedShow(
        title=title,
        tmdb_id=tmdb_id,
        imdb_id=tmdb.imdb_id(tmdb_id),
        episode_title=tmdb.episode_title(tmdb_id, guess.season, guess.episode),
    )


def _resolve_movie(
    tmdb: TmdbClient, request: LinkImportRequest, guess: LinkGuess
) -> ResolvedMovie | list[ShowOption]:
    assert guess.series_title is not None
    if request.tmdb_id is not None:
        tmdb_id = request.tmdb_id
    else:
        movies = tmdb.search_movie(guess.series_title, guess.year)
        if not movies and guess.year is not None:
            movies = tmdb.search_movie(guess.series_title)
        movie = _pick_movie(movies, guess.series_title, guess.year)
        if movie is None:
            return _movie_options(movies)
        tmdb_id = movie.tmdb_id
    details = tmdb.movie_details(tmdb_id)
    return ResolvedMovie(
        title=details.title or guess.series_title,
        year=details.year or guess.year,
        tmdb_id=tmdb_id,
        imdb_id=details.imdb_id,
        runtime_minutes=details.runtime_minutes,
    )


def _classify_by_tmdb(tmdb: TmdbClient, guess: LinkGuess) -> str | list[ShowOption] | None:
    assert guess.series_title is not None
    movies = tmdb.search_movie(guess.series_title, guess.year)
    shows = tmdb.search_tv(guess.series_title)
    movie_hits = [movie for movie in movies if _exact((movie.title, movie.original_title), guess.series_title)]
    show_hits = [show for show in shows if _exact((show.name, show.original_name), guess.series_title)]
    if movie_hits and not show_hits:
        return "movie"
    if show_hits and not movie_hits:
        return "series"
    if not movie_hits and not show_hits:
        return None
    return _movie_options(movie_hits) + _show_options(show_hits)


async def _determine_kind(
    request: LinkImportRequest, guess: LinkGuess, deps: LinkImportDeps
) -> tuple[LinkGuess, list[str], NeedsInput | None]:
    alternatives: list[str] = []
    if request.kind in ("series", "movie"):
        guess = replace(guess, kind=request.kind)
    if guess.kind is None or not guess.complete:
        try:
            resolved, alternatives = await deps.resolve_link(guess)
            guess = link_parser.merge(
                resolved,
                series_title=request.series_title,
                season=request.season,
                episode=request.episode,
                kind=guess.kind,
                year=request.year,
            )
        except AllProvidersFailed:
            logger.warning("AI could not resolve link %s; asking the user", request.url)
    if guess.kind is None and guess.series_title:
        tmdb = deps.tmdb_factory()
        if tmdb is not None:
            try:
                verdict = await asyncio.to_thread(_classify_by_tmdb, tmdb, guess)
            except TmdbError as exc:
                logger.warning("TMDB could not classify %s: %s", guess.series_title, exc)
                verdict = None
            if isinstance(verdict, list):
                return guess, alternatives, NeedsInput(
                    kind="title",
                    message="Это фильм или сериал? Выберите нужный вариант.",
                    guess=guess,
                    options=verdict,
                    alternatives=alternatives,
                )
            if verdict is not None:
                guess = replace(guess, kind=verdict)
    return guess, alternatives, None


def _details_needed(guess: LinkGuess, alternatives: list[str]) -> NeedsInput | None:
    missing = _missing_fields(guess)
    if guess.kind is None:
        missing = ["kind", *missing]
    if not missing:
        return None
    return NeedsInput(
        kind="details",
        message=(
            "Не удалось определить фильм или сериал — уточните."
            if guess.kind is None
            else "Не удалось определить название, сезон или серию — уточните."
        ),
        guess=guess,
        missing=missing,
        alternatives=alternatives,
    )


async def import_from_link(request: LinkImportRequest, deps: LinkImportDeps | None = None) -> ImportResult | NeedsInput:
    deps = deps or LinkImportDeps()
    page_title = await asyncio.to_thread(deps.fetch_page_title, request.url)
    guess = link_parser.merge(
        link_parser.parse_link(request.url, page_title),
        series_title=request.series_title,
        season=request.season,
        episode=request.episode,
        kind=request.kind if request.kind in ("series", "movie") else None,
        year=request.year,
    )
    guess, alternatives, choice = await _determine_kind(request, guess, deps)
    if choice is not None:
        return choice
    needed = _details_needed(guess, alternatives)
    if needed is not None:
        return needed
    if guess.kind == "movie":
        return await _import_movie(request, guess, alternatives, deps)
    return await _import_series(request, guess, alternatives, deps)


async def _import_series(
    request: LinkImportRequest, guess: LinkGuess, alternatives: list[str], deps: LinkImportDeps
) -> ImportResult | NeedsInput:
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
                    message=(
                        "Найдено несколько сериалов — выберите нужный." if resolved else "TMDB не нашёл такой сериал."
                    ),
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
        guessed = await _ai_guess(request, guess, show.title, guess.season, guess.episode, show.episode_title, problems, deps)
        if isinstance(guessed, NeedsInput):
            return guessed
        srt_text = guessed
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


async def _ai_guess(
    request: LinkImportRequest,
    guess: LinkGuess,
    title: str,
    season: int | None,
    episode: int | None,
    label: str | None,
    problems: list[str],
    deps: LinkImportDeps,
) -> str | NeedsInput:
    if not request.allow_ai_guess:
        return NeedsInput(
            kind="subtitles",
            message=(
                "Субтитры не найдены автоматически — загрузите .srt вручную "
                "или разрешите примерный вариант от ИИ."
            ),
            guess=link_parser.merge(guess, series_title=title, season=None, episode=None),
            problems=problems,
        )
    try:
        cues = await deps.guess_dialogue(title, season, episode, label)
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
    return cues_to_srt(cues)


async def _import_movie(
    request: LinkImportRequest, guess: LinkGuess, alternatives: list[str], deps: LinkImportDeps
) -> ImportResult | NeedsInput:
    assert guess.series_title is not None
    problems: list[str] = []
    movie = ResolvedMovie(title=guess.series_title, year=guess.year, tmdb_id=None, imdb_id=None, runtime_minutes=None)
    tmdb = deps.tmdb_factory()
    if tmdb is None:
        problems.append("TMDB: ключ не задан — фильм не уточнён, OpenSubtitles недоступен")
    else:
        try:
            resolved = await asyncio.to_thread(_resolve_movie, tmdb, request, guess)
        except TmdbError as exc:
            problems.append(f"TMDB: {exc}")
        else:
            if isinstance(resolved, list):
                return NeedsInput(
                    kind="title",
                    message="Найдено несколько фильмов — выберите нужный." if resolved else "TMDB не нашёл такой фильм.",
                    guess=guess,
                    options=resolved,
                    alternatives=alternatives,
                )
            movie = resolved

    srt_text: str | None = None
    source: EpisodeSource = "manual"
    cached = subtitle_store.cached_movie(movie.imdb_id, movie.title)
    if cached is not None:
        srt_text = cached.read_text(encoding="utf-8")
        known = await asyncio.to_thread(deps.stored_movie_source, movie.title, movie.imdb_id)
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
        elif movie.imdb_id is None:
            problems.append("OpenSubtitles: нет IMDb ID (нужен TMDB)")
        else:
            try:
                srt_text = await asyncio.to_thread(client.fetch_movie, movie.imdb_id, movie.runtime_minutes)
            except (OpenSubtitlesError, ValueError) as exc:
                problems.append(f"OpenSubtitles: {exc}")
            else:
                if srt_text is None:
                    problems.append("OpenSubtitles: английских субтитров для этого фильма нет")
                source = "opensubtitles"

    if srt_text is None:
        label = str(movie.year) if movie.year else None
        guessed = await _ai_guess(request, guess, movie.title, None, None, label, problems, deps)
        if isinstance(guessed, NeedsInput):
            return guessed
        srt_text = guessed
        source = "ai_guess"

    return await asyncio.to_thread(
        deps.import_movie,
        title_name=movie.title,
        srt_text=srt_text,
        source=source,
        year=movie.year,
        imdb_id=movie.imdb_id,
        tmdb_id=movie.tmdb_id,
        split=request.split_movie,
        part_minutes=request.part_minutes,
    )


async def import_by_title(
    title: str, kind: str | None, year: int | None, deps: LinkImportDeps | None = None
) -> ImportResult | NeedsInput:
    deps = deps or LinkImportDeps()
    known_kind = kind if kind in ("series", "movie") else None
    request = LinkImportRequest(
        url="",
        series_title=title,
        kind=known_kind,
        year=year,
        season=1 if known_kind == "series" else None,
        episode=1 if known_kind == "series" else None,
    )
    guess = LinkGuess(
        url="",
        series_title=title,
        season=request.season,
        episode=request.episode,
        kind=known_kind,
        year=year,
    )
    guess, alternatives, choice = await _determine_kind(request, guess, deps)
    if choice is not None:
        return choice
    if guess.kind == "series" and (guess.season is None or guess.episode is None):
        guess = replace(guess, season=guess.season or 1, episode=guess.episode or 1)
    needed = _details_needed(guess, alternatives)
    if needed is not None:
        return needed
    if guess.kind == "movie":
        return await _import_movie(request, guess, alternatives, deps)
    return await _import_series(request, guess, alternatives, deps)
