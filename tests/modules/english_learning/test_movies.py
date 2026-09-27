from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning import cefr, link_import, service_layer, subtitle_store
from modules.english_learning.credentials import OpenSubtitlesCredentials
from modules.english_learning.domain import Episode, SubtitleCue, Title
from modules.english_learning.link_import import LinkImportDeps, LinkImportRequest, NeedsInput
from modules.english_learning.link_parser import LinkGuess, parse_link
from modules.english_learning.movie_parts import split_parts
from modules.english_learning.opensubtitles import OpenSubtitlesClient, SubtitleFile, matches_runtime
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.srt_parser import cues_to_srt
from modules.english_learning.tmdb import TmdbMovie, TmdbMovieDetails, TmdbShow
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer

MINUTE = 60_000


def _srt(lines: list[tuple[int, str]]) -> str:
    return cues_to_srt([SubtitleCue(i + 1, ms, ms + 2000, text) for i, (ms, text) in enumerate(lines)])


MOVIE_SRT = _srt(
    [
        (1 * MINUTE, "I am honest with you."),
        (5 * MINUTE, "The house is quiet tonight."),
        (19 * MINUTE + 30_000, "Wait for it."),
        (21 * MINUTE, "Somebody opened the door."),
        (30 * MINUTE, "We decided to be honest."),
        (44 * MINUTE, "The house is empty."),
    ]
)


class _Tmdb:
    def __init__(self, movies: list[TmdbMovie], shows: list[TmdbShow] | None = None) -> None:
        self.movies = movies
        self.shows = shows or []
        self.searches: list[tuple[str, int | None]] = []

    def search_movie(self, query: str, year: int | None = None) -> list[TmdbMovie]:
        self.searches.append((query, year))
        return [movie for movie in self.movies if year is None or movie.year == year]

    def search_tv(self, query: str) -> list[TmdbShow]:
        return self.shows

    def movie_details(self, tmdb_id: int) -> TmdbMovieDetails:
        movie = next(movie for movie in self.movies if movie.tmdb_id == tmdb_id)
        return TmdbMovieDetails(tmdb_id, movie.title, movie.year, f"tt{tmdb_id:07d}", 128)


class _OpenSubtitles:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def fetch_movie(self, imdb_id: str, runtime: int | None) -> str | None:
        self.calls.append((imdb_id, runtime))
        return MOVIE_SRT


HOLMES_2009 = TmdbMovie(10528, "Sherlock Holmes", "Sherlock Holmes", 2009, 60.0, "/h2009.jpg")
HOLMES_1922 = TmdbMovie(55, "Sherlock Holmes", "Sherlock Holmes", 1922, 3.0, None)


def _deps(tmdb: Any, opensubtitles: Any, page_title: str | None) -> tuple[LinkImportDeps, dict[str, Any]]:
    captured: dict[str, Any] = {}

    def fake_movie(**kwargs: Any) -> ImportResult:
        captured.update(kwargs)
        title = Title(name=kwargs["title_name"], kind="movie", year=kwargs["year"], id=1)
        return ImportResult(title=title, episode=Episode(title_id=1, source=kwargs["source"], id=3), words=[])

    async def no_ai(guess: LinkGuess) -> tuple[LinkGuess, list[str]]:
        raise AllProvidersFailed([])

    deps = LinkImportDeps(
        fetch_page_title=lambda url: page_title,
        resolve_link=no_ai,
        tmdb_factory=lambda: tmdb,
        opensubtitles_factory=lambda: opensubtitles,
        import_movie=fake_movie,
        stored_movie_source=lambda *args: None,
    )
    return deps, captured


def test_parse_link_reads_movie_year() -> None:
    guess = parse_link("https://x.tv/m/1", "Sherlock Holmes (2009) — watch online")

    assert (guess.series_title, guess.year, guess.kind) == ("Sherlock Holmes", 2009, None)


def test_movie_link_is_detected_and_imported_with_year_choice() -> None:
    tmdb = _Tmdb([HOLMES_1922, HOLMES_2009])
    opensubtitles = _OpenSubtitles()
    deps, captured = _deps(tmdb, opensubtitles, "Sherlock Holmes (2009) | Watch")

    result = asyncio.run(link_import.import_from_link(LinkImportRequest(url="https://x.tv/m/1"), deps))

    assert isinstance(result, ImportResult)
    assert (captured["title_name"], captured["year"], captured["imdb_id"]) == ("Sherlock Holmes", 2009, "tt0010528")
    assert captured["source"] == "opensubtitles"
    assert captured["split"] is True and captured["part_minutes"] == 20
    assert opensubtitles.calls == [("tt0010528", 128)]


def test_same_name_movies_without_year_ask_to_choose() -> None:
    tmdb = _Tmdb([HOLMES_1922, HOLMES_2009])
    deps, captured = _deps(tmdb, _OpenSubtitles(), "Sherlock Holmes | Watch")

    first = asyncio.run(link_import.import_from_link(LinkImportRequest(url="https://x.tv/m/1", kind="movie"), deps))

    assert isinstance(first, NeedsInput) and first.kind == "title"
    assert {(option.year, option.kind) for option in first.options} == {(1922, "movie"), (2009, "movie")}
    assert any(option.poster_url and option.poster_url.endswith("/h2009.jpg") for option in first.options)

    second = asyncio.run(
        link_import.import_from_link(LinkImportRequest(url="https://x.tv/m/1", kind="movie", tmdb_id=10528), deps)
    )
    assert isinstance(second, ImportResult)
    assert captured["year"] == 2009


def test_ambiguous_movie_or_series_offers_both() -> None:
    tmdb = _Tmdb([TmdbMovie(1, "Fargo", "Fargo", 1996, 30.0)], [TmdbShow(2, "Fargo", "Fargo", 2014, 40.0)])
    deps, _ = _deps(tmdb, _OpenSubtitles(), "Fargo | Watch")

    result = asyncio.run(link_import.import_from_link(LinkImportRequest(url="https://x.tv/f"), deps))

    assert isinstance(result, NeedsInput) and result.kind == "title"
    assert {option.kind for option in result.options} == {"movie", "series"}


def test_split_parts_cuts_at_the_nearest_pause() -> None:
    cues = [SubtitleCue(i + 1, ms, ms + 1500, "x") for i, ms in enumerate(range(0, 50 * MINUTE, 10_000))]
    cues = [cue for cue in cues if not 19 * MINUTE + 40_000 < cue.start_ms < 20 * MINUTE + 14_000]

    parts = split_parts(cues, 20)

    assert parts[0].start_ms == 0
    assert parts[0].end_ms == 20 * MINUTE + 20_000
    assert parts[1].start_ms == parts[0].end_ms
    assert parts[-1].end_ms == cues[-1].end_ms
    assert [part.number for part in parts] == [1, 2, 3]
    assert 40 * MINUTE - 5 * MINUTE <= parts[2].start_ms <= 40 * MINUTE + 5 * MINUTE


def test_split_parts_clamps_minutes_and_keeps_short_movies_whole() -> None:
    cues = [SubtitleCue(1, 0, 1000, "a"), SubtitleCue(2, 24 * MINUTE, 24 * MINUTE + 1000, "b")]

    assert len(split_parts(cues, 20)) == 1
    assert len(split_parts(cues, 5)) == 2


def test_movie_parts_get_words_from_their_first_occurrence(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    result = service_layer.import_movie(
        title_name="Sherlock Holmes",
        year=2009,
        srt_text=MOVIE_SRT,
        source="manual",
        imdb_id="tt0988045",
        lemmatizer=FakeLemmatizer(),
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )

    assert [episode.code for episode in result.episodes] == ["Часть 1 · 00:00–19:30", "Часть 2 · 19:30–44:02"]
    first, second = (episode.id for episode in result.episodes)
    part_one = {word.lemma for word in service_layer.episode_words(first or 0, uow_factory)}
    part_two = {word.lemma for word in service_layer.episode_words(second or 0, uow_factory)}
    assert {"honest", "house"} <= part_one
    assert "decide" in part_two
    assert "honest" not in part_two and "house" not in part_two
    assert subtitle_store.cached_movie("tt0988045", "Sherlock Holmes") is not None

    library = service_layer.library(uow_factory)
    assert library[0].display_name.startswith("Sherlock Holmes (2009) — ")
    assert library[0].episodes[0].display_name.startswith("Часть 1 · 00:00–19:30 — ")


def test_reimport_keeps_existing_parts(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    kwargs: dict[str, Any] = {
        "title_name": "Sherlock Holmes",
        "year": 2009,
        "srt_text": MOVIE_SRT,
        "source": "manual",
        "lemmatizer": FakeLemmatizer(),
        "uow_factory": uow_factory,
        "ensure_cefr": lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    }
    first = service_layer.import_movie(**kwargs)
    second = service_layer.import_movie(**{**kwargs, "part_minutes": 10})

    assert [episode.id for episode in first.episodes] == [episode.id for episode in second.episodes]


def test_unsplit_movie_is_a_single_episode(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    result = service_layer.import_movie(
        title_name="Heat",
        srt_text=MOVIE_SRT,
        source="manual",
        split=False,
        lemmatizer=FakeLemmatizer(),
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )

    assert [episode.code for episode in result.episodes] == ["Фильм"]


class _StubClient(OpenSubtitlesClient):
    def __init__(self, files: list[SubtitleFile], texts: dict[int, str]) -> None:
        super().__init__(OpenSubtitlesCredentials("key", "user", "pass"))
        self.files = files
        self.texts = texts
        self.downloaded: list[int] = []

    def search_movie(self, imdb_id: str) -> list[SubtitleFile]:
        return self.files

    def download(self, file_id: int) -> str:
        self.downloaded.append(file_id)
        return self.texts[file_id]


def test_fetch_movie_prefers_downloads_then_matching_runtime() -> None:
    short = _srt([(0, "a"), (30 * MINUTE, "b")])
    full = _srt([(0, "a"), (120 * MINUTE, "b")])
    files = [
        SubtitleFile(1, "cam", 900, False, False),
        SubtitleFile(2, "bluray", 500, False, False),
        SubtitleFile(3, "mt", 5000, False, True),
    ]
    client = _StubClient(files, {1: short, 2: full})

    assert client.fetch_movie("tt1", 128) == full
    assert client.downloaded == [1, 2]
    assert matches_runtime(full, 128) and not matches_runtime(short, 128)


@pytest.mark.parametrize("runtime", [None, 128])
def test_fetch_movie_stops_after_first_match(runtime: int | None) -> None:
    full = _srt([(0, "a"), (120 * MINUTE, "b")])
    client = _StubClient([SubtitleFile(1, "x", 10, False, False), SubtitleFile(2, "y", 5, False, False)], {1: full, 2: full})

    client.fetch_movie("tt1", runtime)

    assert client.downloaded == [1]
