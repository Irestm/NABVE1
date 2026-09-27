from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from modules.english_learning.credentials import OpenSubtitlesCredentials
from modules.english_learning.srt_parser import SrtParseError, parse_srt

OPENSUBTITLES_BASE_URL = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "NABVE v0.3"
_TIMEOUT_SECONDS = 20.0
MOVIE_DOWNLOAD_ATTEMPTS = 2
MIN_RUNTIME_RATIO = 0.75
MAX_RUNTIME_RATIO = 1.1


class OpenSubtitlesError(RuntimeError):
    pass


class OpenSubtitlesAuthError(OpenSubtitlesError):
    pass


class OpenSubtitlesQuotaError(OpenSubtitlesError):
    pass


@dataclass(frozen=True)
class SubtitleFile:
    file_id: int
    release: str
    download_count: int
    hearing_impaired: bool
    machine_translated: bool


def _imdb_number(imdb_id: str) -> str:
    digits = imdb_id.lower().removeprefix("tt").lstrip("0")
    if not digits.isdigit():
        raise ValueError(f"Некорректный IMDb ID: {imdb_id}")
    return digits


class OpenSubtitlesClient:
    def __init__(self, credentials: OpenSubtitlesCredentials, http: httpx.Client | None = None) -> None:
        self._credentials = credentials
        self._http = http or httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=True)
        self._token: str | None = None
        self._base_url = OPENSUBTITLES_BASE_URL

    def _headers(self, *, auth: bool = False) -> dict[str, str]:
        headers = {
            "Api-Key": self._credentials.api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _check(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise OpenSubtitlesAuthError("OpenSubtitles отклонил ключ или логин")
        if response.status_code in (406, 429):
            raise OpenSubtitlesQuotaError("Исчерпан дневной лимит скачиваний OpenSubtitles")
        if response.status_code >= 400:
            raise OpenSubtitlesError(f"OpenSubtitles вернул {response.status_code}")
        return response.json()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise OpenSubtitlesError(f"OpenSubtitles недоступен: {exc}") from exc

    def login(self) -> None:
        if not self._credentials.has_account:
            raise OpenSubtitlesAuthError("Для скачивания нужен логин и пароль OpenSubtitles")
        payload = self._check(
            self._request(
                "POST",
                f"{OPENSUBTITLES_BASE_URL}/login",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"username": self._credentials.username, "password": self._credentials.password},
            )
        )
        self._token = str(payload["token"])
        base_url = payload.get("base_url")
        if base_url:
            self._base_url = f"https://{str(base_url).removeprefix('https://').rstrip('/')}/api/v1"

    def search(self, imdb_id: str, season: int, episode: int) -> list[SubtitleFile]:
        return self._search(
            {
                "episode_number": episode,
                "languages": "en",
                "parent_imdb_id": _imdb_number(imdb_id),
                "season_number": season,
            }
        )

    def search_movie(self, imdb_id: str) -> list[SubtitleFile]:
        return self._search({"imdb_id": _imdb_number(imdb_id), "languages": "en", "type": "movie"})

    def _search(self, params: dict[str, Any]) -> list[SubtitleFile]:
        payload = self._check(
            self._request("GET", f"{OPENSUBTITLES_BASE_URL}/subtitles", headers=self._headers(), params=params)
        )
        files: list[SubtitleFile] = []
        for item in payload.get("data", []):
            attributes = item.get("attributes", {})
            for file in attributes.get("files", []):
                files.append(
                    SubtitleFile(
                        file_id=int(file["file_id"]),
                        release=str(attributes.get("release") or ""),
                        download_count=int(attributes.get("download_count") or 0),
                        hearing_impaired=bool(attributes.get("hearing_impaired")),
                        machine_translated=bool(
                            attributes.get("machine_translated") or attributes.get("ai_translated")
                        ),
                    )
                )
        return files

    def best_file(self, files: list[SubtitleFile]) -> SubtitleFile | None:
        usable = [file for file in files if not file.machine_translated] or files
        if not usable:
            return None
        return max(usable, key=lambda file: (not file.hearing_impaired, file.download_count))

    def download(self, file_id: int) -> str:
        if self._token is None:
            self.login()
        payload = self._check(
            self._request(
                "POST",
                f"{self._base_url}/download",
                headers={**self._headers(auth=True), "Content-Type": "application/json"},
                json={"file_id": file_id, "sub_format": "srt"},
            )
        )
        link = payload.get("link")
        if not link:
            raise OpenSubtitlesError("OpenSubtitles не вернул ссылку на файл")
        response = self._request("GET", str(link), headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            raise OpenSubtitlesError(f"Не удалось скачать файл субтитров ({response.status_code})")
        return response.content.decode("utf-8", errors="replace")

    def fetch_episode(self, imdb_id: str, season: int, episode: int) -> str | None:
        best = self.best_file(self.search(imdb_id, season, episode))
        return self.download(best.file_id) if best is not None else None

    def movie_candidates(self, files: list[SubtitleFile]) -> list[SubtitleFile]:
        usable = [file for file in files if not file.machine_translated] or files
        return sorted(usable, key=lambda file: (file.download_count, not file.hearing_impaired), reverse=True)

    def fetch_movie(self, imdb_id: str, runtime_minutes: int | None) -> str | None:
        candidates = self.movie_candidates(self.search_movie(imdb_id))
        fallback: str | None = None
        for file in candidates[:MOVIE_DOWNLOAD_ATTEMPTS]:
            text = self.download(file.file_id)
            fallback = fallback or text
            if runtime_minutes is None or matches_runtime(text, runtime_minutes):
                return text
        return fallback


def matches_runtime(srt_text: str, runtime_minutes: int) -> bool:
    try:
        cues = parse_srt(srt_text)
    except SrtParseError:
        return False
    ratio = cues[-1].end_ms / (runtime_minutes * 60_000)
    return MIN_RUNTIME_RATIO <= ratio <= MAX_RUNTIME_RATIO
