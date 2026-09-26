from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TMDB_BASE_URL = "https://api.themoviedb.org/3"
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
