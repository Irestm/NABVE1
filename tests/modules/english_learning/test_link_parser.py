from __future__ import annotations

import pytest

from modules.english_learning.link_parser import merge, parse_link, youtube_id


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        ("https://www.netflix.com/watch/70196252", "Breaking Bad: Season 1, Episode 3 - Netflix", ("Breaking Bad", 1, 3)),
        ("https://example.tv/shows/the-office-us/season-2/episode-5", None, ("The Office Us", 2, 5)),
        ("https://site.ru/serial/friends-s03e10-online", None, ("Friends", 3, 10)),
        ("https://www.hbo.com/the-last-of-us/season-1/episode-3", "The Last of Us", ("The Last Of Us", 1, 3)),
        ("https://x.ru/646-vo-vse-tyazhkie/", "Во все тяжкие (2008) 1 сезон 3 серия смотреть онлайн", ("Во Все Тяжкие", 1, 3)),
        ("https://x.tv/watch", "Dark 2x04 | Stream", ("Dark", 2, 4)),
    ],
)
def test_parse_link_extracts_series_season_episode(url: str, title: str | None, expected: tuple[str, int, int]) -> None:
    guess = parse_link(url, title)

    assert (guess.series_title, guess.season, guess.episode) == expected
    assert guess.complete


def test_parse_link_without_episode_is_incomplete() -> None:
    guess = parse_link("https://example.com/watch/dark", None)

    assert guess.series_title == "Dark"
    assert guess.episode is None
    assert not guess.complete


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=abc123&t=5", "abc123"),
        ("https://youtu.be/xyz789", "xyz789"),
        ("https://www.youtube.com/shorts/short1", "short1"),
        ("https://vimeo.com/123", None),
    ],
)
def test_youtube_id(url: str, expected: str | None) -> None:
    assert youtube_id(url) == expected


def test_merge_prefers_explicit_values() -> None:
    guess = parse_link("https://site.ru/serial/friends-s03e10-online")

    merged = merge(guess, series_title="Friends (1994)", season=None, episode=11)

    assert (merged.series_title, merged.season, merged.episode) == ("Friends (1994)", 3, 11)
