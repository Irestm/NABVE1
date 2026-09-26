from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from modules.english_learning.credentials import OpenSubtitlesCredentials
from modules.english_learning.opensubtitles import (
    OpenSubtitlesAuthError,
    OpenSubtitlesClient,
    OpenSubtitlesQuotaError,
    SubtitleFile,
)
from modules.english_learning.tmdb import TMDB_BASE_URL, TmdbAuthError, TmdbClient

Handler = Callable[[httpx.Request], httpx.Response]


def _tmdb(handler: Handler, key: str = "v3key") -> TmdbClient:
    return TmdbClient(key, httpx.Client(base_url=TMDB_BASE_URL, transport=httpx.MockTransport(handler)))


def test_tmdb_search_external_ids_and_episode_title() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/search/tv"):
            return httpx.Response(200, json={"results": [{"id": 1396, "name": "Breaking Bad", "original_name": "Breaking Bad", "first_air_date": "2008-01-20", "popularity": 300}]})
        if path.endswith("/external_ids"):
            return httpx.Response(200, json={"imdb_id": "tt0903747"})
        if path.endswith("/season/1/episode/3"):
            return httpx.Response(200, json={"name": "...And the Bag's in the River"})
        return httpx.Response(404)

    client = _tmdb(handler)

    shows = client.search_tv("breaking bad")
    assert shows[0].tmdb_id == 1396 and shows[0].year == 2008
    assert client.imdb_id(1396) == "tt0903747"
    assert client.episode_title(1396, 1, 3) == "...And the Bag's in the River"
    assert client.episode_title(1396, 9, 9) is None
    assert seen[0].url.params["api_key"] == "v3key"


def test_tmdb_uses_bearer_for_v4_tokens() -> None:
    headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"results": []})

    _tmdb(handler, key="eyJhbGciOi.token").search_tv("x")

    assert headers == ["Bearer eyJhbGciOi.token"]


def test_tmdb_auth_error() -> None:
    with pytest.raises(TmdbAuthError):
        _tmdb(lambda request: httpx.Response(401)).search_tv("x")


def _opensubtitles(handler: Handler, *, account: bool = True) -> OpenSubtitlesClient:
    credentials = OpenSubtitlesCredentials("os-key", "user" if account else None, "pass" if account else None)
    return OpenSubtitlesClient(credentials, httpx.Client(transport=httpx.MockTransport(handler)))


def _search_payload() -> dict[str, object]:
    return {
        "data": [
            {"attributes": {"release": "HI", "download_count": 900, "hearing_impaired": True, "files": [{"file_id": 1}]}},
            {"attributes": {"release": "best", "download_count": 500, "hearing_impaired": False, "files": [{"file_id": 2}]}},
            {"attributes": {"release": "mt", "download_count": 9999, "machine_translated": True, "files": [{"file_id": 3}]}},
        ]
    }


def test_opensubtitles_search_login_and_download_best_file() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.host.endswith("opensubtitles.com"):
            assert request.headers["Api-Key"] == "os-key"
        if request.url.path.endswith("/subtitles"):
            assert request.url.params["parent_imdb_id"] == "903747"
            assert request.url.params["languages"] == "en"
            return httpx.Response(200, json=_search_payload())
        if request.url.path.endswith("/login"):
            assert json.loads(request.content) == {"username": "user", "password": "pass"}
            return httpx.Response(200, json={"token": "tok", "base_url": "vip-api.opensubtitles.com"})
        if request.url.path.endswith("/download"):
            assert request.url.host == "vip-api.opensubtitles.com"
            assert request.headers["Authorization"] == "Bearer tok"
            assert json.loads(request.content)["file_id"] == 2
            return httpx.Response(200, json={"link": "https://dl.example/file.srt"})
        if request.url.host == "dl.example":
            return httpx.Response(200, content=b"1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        return httpx.Response(404)

    text = _opensubtitles(handler).fetch_episode("tt0903747", 1, 3)

    assert text is not None and "Hi" in text
    assert [path.rsplit("/", 1)[-1] for _method, path in calls] == ["subtitles", "login", "download", "file.srt"]


def test_best_file_prefers_human_non_hi_popular() -> None:
    client = _opensubtitles(lambda request: httpx.Response(500))
    files = [
        SubtitleFile(1, "a", 900, True, False),
        SubtitleFile(2, "b", 500, False, False),
        SubtitleFile(3, "c", 9999, False, True),
    ]

    best = client.best_file(files)

    assert best is not None and best.file_id == 2


def test_opensubtitles_download_requires_an_account() -> None:
    client = _opensubtitles(lambda request: httpx.Response(200, json=_search_payload()), account=False)

    with pytest.raises(OpenSubtitlesAuthError):
        client.fetch_episode("tt0903747", 1, 3)


def test_opensubtitles_quota_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/subtitles"):
            return httpx.Response(200, json=_search_payload())
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(406, json={"message": "quota"})

    with pytest.raises(OpenSubtitlesQuotaError):
        _opensubtitles(handler).fetch_episode("tt0903747", 1, 3)


def test_opensubtitles_no_results_returns_none() -> None:
    assert _opensubtitles(lambda request: httpx.Response(200, json={"data": []})).fetch_episode("tt1", 1, 1) is None
