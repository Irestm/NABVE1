from __future__ import annotations

import asyncio
from typing import Any

import pytest

from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning import link_import, subtitle_store
from modules.english_learning.domain import Episode, Series, SubtitleCue
from modules.english_learning.link_import import LinkImportDeps, LinkImportRequest, NeedsInput
from modules.english_learning.link_parser import LinkGuess
from modules.english_learning.opensubtitles import OpenSubtitlesQuotaError
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.tmdb import TmdbShow
from modules.english_learning.youtube_subs import YoutubeSubtitlesError

SRT = "1\n00:00:01,000 --> 00:00:02,000\nI figured it out.\n"


class _Tmdb:
    def __init__(self, shows: list[TmdbShow]) -> None:
        self.shows = shows

    def search_tv(self, query: str) -> list[TmdbShow]:
        return self.shows

    def english_name(self, tmdb_id: int) -> str | None:
        return next((show.name for show in self.shows if show.tmdb_id == tmdb_id), None)

    def imdb_id(self, tmdb_id: int) -> str | None:
        return f"tt{tmdb_id:07d}"

    def episode_title(self, tmdb_id: int, season: int, episode: int) -> str | None:
        return "Pilot"


class _OpenSubtitles:
    def __init__(self, text: str | None = SRT, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    def fetch_episode(self, imdb_id: str, season: int, episode: int) -> str | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.text


BB = TmdbShow(1396, "Breaking Bad", "Breaking Bad", 2008, 300.0)


def _deps(
    *,
    page_title: str | None = "Breaking Bad S01E03 | Watch",
    tmdb: Any = None,
    opensubtitles: Any = None,
    youtube: Any = None,
    resolve: Any = None,
    guess_lines: Any = None,
) -> tuple[LinkImportDeps, dict[str, Any]]:
    captured: dict[str, Any] = {}

    def fake_import(**kwargs: Any) -> ImportResult:
        captured.update(kwargs)
        return ImportResult(
            series=Series(title=kwargs["series_title"], id=1),
            episode=Episode(series_id=1, season=kwargs["season"], episode=kwargs["episode"], source=kwargs["source"], id=7),
            words=[],
        )

    async def default_resolve(guess: LinkGuess) -> tuple[LinkGuess, list[str]]:
        raise AllProvidersFailed([])

    async def default_guess(*args: Any) -> list[SubtitleCue]:
        return [SubtitleCue(1, 0, 1000, "I decided to be honest.")]

    def default_youtube(url: str) -> tuple[str, str | None]:
        raise YoutubeSubtitlesError("no subs")

    deps = LinkImportDeps(
        fetch_page_title=lambda url: page_title,
        resolve_link=resolve or default_resolve,
        guess_dialogue=guess_lines or default_guess,
        tmdb_factory=lambda: tmdb,
        opensubtitles_factory=lambda: opensubtitles,
        fetch_youtube=youtube or default_youtube,
        import_subtitles=fake_import,
        stored_source=lambda *args: None,
    )
    return deps, captured


def _run(request: LinkImportRequest, deps: LinkImportDeps) -> Any:
    return asyncio.run(link_import.import_from_link(request, deps))


def test_full_chain_tmdb_then_opensubtitles() -> None:
    deps, captured = _deps(tmdb=_Tmdb([BB]), opensubtitles=_OpenSubtitles())

    result = _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert isinstance(result, ImportResult)
    assert captured["source"] == "opensubtitles"
    assert captured["imdb_id"] == "tt0001396"
    assert captured["episode_title"] == "Pilot"
    assert (captured["season"], captured["episode"]) == (1, 3)


def test_missing_details_come_back_as_needs_input() -> None:
    deps, _ = _deps(page_title="Some random page")

    result = _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert isinstance(result, NeedsInput)
    assert result.kind == "details"
    assert set(result.missing) >= {"season", "episode"}


def test_ai_fills_missing_details() -> None:
    async def resolve(guess: LinkGuess) -> tuple[LinkGuess, list[str]]:
        return LinkGuess(guess.url, "Breaking Bad", 2, 1), ["Breaking Bad (2008)"]

    deps, captured = _deps(page_title="Some random page", tmdb=_Tmdb([BB]), opensubtitles=_OpenSubtitles(), resolve=resolve)

    result = _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert isinstance(result, ImportResult)
    assert (captured["season"], captured["episode"]) == (2, 1)


def test_ambiguous_series_returns_options_and_choice_resolves_it() -> None:
    shows = [TmdbShow(1, "The Office", "The Office", 2005, 100.0), TmdbShow(2, "The Office", "The Office", 2001, 90.0)]
    deps, captured = _deps(page_title="The Office S02E05", tmdb=_Tmdb(shows), opensubtitles=_OpenSubtitles())

    first = _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert isinstance(first, NeedsInput) and first.kind == "series"
    assert [option.tmdb_id for option in first.options] == [1, 2]

    second = _run(LinkImportRequest(url="https://x.tv/watch/1", tmdb_id=2), deps)

    assert isinstance(second, ImportResult)
    assert captured["tmdb_id"] == 2


def test_youtube_link_uses_yt_dlp_first() -> None:
    opensubtitles = _OpenSubtitles()
    deps, captured = _deps(
        page_title="Friends 1x05 - YouTube",
        tmdb=_Tmdb([TmdbShow(1668, "Friends", "Friends", 1994, 200.0)]),
        opensubtitles=opensubtitles,
        youtube=lambda url: (SRT, "Friends clip"),
    )

    _run(LinkImportRequest(url="https://www.youtube.com/watch?v=abc"), deps)

    assert captured["source"] == "youtube"
    assert opensubtitles.calls == 0


def test_cached_subtitles_skip_downloads(tmp_path: Any) -> None:
    subtitle_store.save("tt0001396", "Breaking Bad", 1, 3, SRT)
    opensubtitles = _OpenSubtitles()
    deps, captured = _deps(tmdb=_Tmdb([BB]), opensubtitles=opensubtitles)

    _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert opensubtitles.calls == 0
    assert captured["srt_text"] == SRT


def test_without_subtitles_asks_for_upload_or_ai_and_lists_problems() -> None:
    deps, _ = _deps(tmdb=_Tmdb([BB]), opensubtitles=_OpenSubtitles(error=OpenSubtitlesQuotaError("limit")))

    result = _run(LinkImportRequest(url="https://x.tv/watch/1"), deps)

    assert isinstance(result, NeedsInput) and result.kind == "subtitles"
    assert any("limit" in problem for problem in result.problems)


def test_ai_guess_marks_the_source() -> None:
    deps, captured = _deps(tmdb=None, opensubtitles=None)

    result = _run(LinkImportRequest(url="https://x.tv/watch/1", allow_ai_guess=True), deps)

    assert isinstance(result, ImportResult)
    assert captured["source"] == "ai_guess"
    assert "honest" in captured["srt_text"]


def test_ai_guess_failure_falls_back_to_manual_upload_request() -> None:
    async def failing(*args: Any) -> list[SubtitleCue]:
        raise AllProvidersFailed([("ollama", "down")])

    deps, _ = _deps(tmdb=None, opensubtitles=None, guess_lines=failing)

    result = _run(LinkImportRequest(url="https://x.tv/watch/1", allow_ai_guess=True), deps)

    assert isinstance(result, NeedsInput) and result.kind == "subtitles"


def test_pick_show_prefers_unique_exact_title() -> None:
    shows = [TmdbShow(1, "Dark", "Dark", 2017, 10.0), TmdbShow(2, "Dark Matter", "Dark Matter", 2015, 50.0)]

    picked = link_import._pick_show(shows, "dark")

    assert picked is not None and picked.tmdb_id == 1


@pytest.mark.parametrize("popularity", [300.0, 100.0])
def test_pick_show_needs_a_clear_popularity_winner(popularity: float) -> None:
    shows = [TmdbShow(1, "A", "A", None, popularity), TmdbShow(2, "B", "B", None, 100.0)]

    picked = link_import._pick_show(shows, "zzz")

    assert (picked is not None) == (popularity == 300.0)
