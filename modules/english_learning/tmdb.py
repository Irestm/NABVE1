from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_POSTER_URL = "https://image.tmdb.org/t/p/w185"
_TIMEOUT_SECONDS = 15.0


class TmdbError(RuntimeError):
    pass


class TmdbAuthError(TmdbError):
    pass


@dataclass(frozen=True)
class TmdbShow:
    tmdb_id: int
    name: str
    original_name: str
    year: int | None
    popularity: float
    poster_path: str | None = None


@dataclass(frozen=True)
class TmdbMovie:
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    popularity: float
    poster_path: str | None = None


@dataclass(frozen=True)
class TmdbMovieDetails:
    tmdb_id: int
    title: str
    year: int | None
    imdb_id: str | None
    runtime_minutes: int | None


def poster_url(path: str | None) -> str | None:
    return f"{TMDB_POSTER_URL}{path}" if path else None


def _year(value: object) -> int | None:
    text = str(value or "")
    return int(text[:4]) if text[:4].isdigit() else None


class TmdbClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._http = http or httpx.Client(base_url=TMDB_BASE_URL, timeout=_TIMEOUT_SECONDS)

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._api_key.startswith("eyJ"):
            return {"Authorization": f"Bearer {self._api_key}"}, {}
        return {}, {"api_key": self._api_key}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers, auth_params = self._auth()
        try:
            response = self._http.get(path, params={**(params or {}), **auth_params}, headers=headers)
        except httpx.HTTPError as exc:
            raise TmdbError(f"TMDB недоступен: {exc}") from exc
        if response.status_code == 401:
            raise TmdbAuthError("TMDB отклонил ключ")
        if response.status_code == 404:
            raise TmdbError("TMDB: не найдено")
        if response.status_code >= 400:
            raise TmdbError(f"TMDB вернул {response.status_code}")
        return response.json()

    def search_tv(self, query: str) -> list[TmdbShow]:
        payload = self._get("/search/tv", {"query": query, "include_adult": "false"})
        shows: list[TmdbShow] = []
        for item in payload.get("results", []):
            first_air = str(item.get("first_air_date") or "")
            shows.append(
                TmdbShow(
                    tmdb_id=int(item["id"]),
                    name=str(item.get("name") or item.get("original_name") or ""),
                    original_name=str(item.get("original_name") or ""),
                    year=int(first_air[:4]) if first_air[:4].isdigit() else None,
                    popularity=float(item.get("popularity") or 0.0),
                    poster_path=item.get("poster_path") or None,
                )
            )
        return shows

    def imdb_id(self, tmdb_id: int) -> str | None:
        value = self._get(f"/tv/{tmdb_id}/external_ids").get("imdb_id")
        return str(value) if value else None

    def episode_title(self, tmdb_id: int, season: int, episode: int) -> str | None:
        try:
            value = self._get(f"/tv/{tmdb_id}/season/{season}/episode/{episode}").get("name")
        except TmdbAuthError:
            raise
        except TmdbError:
            return None
        return str(value) if value else None

    def english_name(self, tmdb_id: int) -> str | None:
        value = self._get(f"/tv/{tmdb_id}", {"language": "en-US"}).get("name")
        return str(value) if value else None

    def search_movie(self, query: str, year: int | None = None) -> list[TmdbMovie]:
        params: dict[str, Any] = {"query": query, "include_adult": "false"}
        if year is not None:
            params["year"] = year
        payload = self._get("/search/movie", params)
        return [
            TmdbMovie(
                tmdb_id=int(item["id"]),
                title=str(item.get("title") or item.get("original_title") or ""),
                original_title=str(item.get("original_title") or ""),
                year=_year(item.get("release_date")),
                popularity=float(item.get("popularity") or 0.0),
                poster_path=item.get("poster_path") or None,
            )
            for item in payload.get("results", [])
        ]

    def movie_details(self, tmdb_id: int) -> TmdbMovieDetails:
        payload = self._get(f"/movie/{tmdb_id}", {"language": "en-US"})
        runtime = payload.get("runtime")
        imdb = payload.get("imdb_id")
        return TmdbMovieDetails(
            tmdb_id=tmdb_id,
            title=str(payload.get("title") or payload.get("original_title") or ""),
            year=_year(payload.get("release_date")),
            imdb_id=str(imdb) if imdb else None,
            runtime_minutes=int(runtime) if isinstance(runtime, int) and runtime > 0 else None,
        )
