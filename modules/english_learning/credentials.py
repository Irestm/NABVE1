from __future__ import annotations

from dataclasses import dataclass

from core.secret_store import delete_secret, get_secret, store_secret

TMDB_API_KEY = "english_tmdb_api_key"
OPENSUBTITLES_API_KEY = "english_opensubtitles_api_key"
OPENSUBTITLES_USERNAME = "english_opensubtitles_username"
OPENSUBTITLES_PASSWORD = "english_opensubtitles_password"

ALL_SECRETS: tuple[str, ...] = (TMDB_API_KEY, OPENSUBTITLES_API_KEY, OPENSUBTITLES_USERNAME, OPENSUBTITLES_PASSWORD)


@dataclass(frozen=True)
class OpenSubtitlesCredentials:
    api_key: str
    username: str | None
    password: str | None

    @property
    def has_account(self) -> bool:
        return bool(self.username and self.password)


@dataclass(frozen=True)
class CredentialsStatus:
    tmdb: bool
    opensubtitles_api_key: bool
    opensubtitles_account: bool


def tmdb_key() -> str | None:
    return get_secret(TMDB_API_KEY)


def opensubtitles() -> OpenSubtitlesCredentials | None:
    api_key = get_secret(OPENSUBTITLES_API_KEY)
    if not api_key:
        return None
    return OpenSubtitlesCredentials(
        api_key=api_key, username=get_secret(OPENSUBTITLES_USERNAME), password=get_secret(OPENSUBTITLES_PASSWORD)
    )


def status() -> CredentialsStatus:
    credentials = opensubtitles()
    return CredentialsStatus(
        tmdb=tmdb_key() is not None,
        opensubtitles_api_key=credentials is not None,
        opensubtitles_account=credentials is not None and credentials.has_account,
    )


def update(values: dict[str, str | None]) -> CredentialsStatus:
    for name, value in values.items():
        if name not in ALL_SECRETS:
            raise KeyError(name)
        if value is None:
            continue
        if value.strip():
            store_secret(name, value.strip())
        else:
            delete_secret(name)
    return status()
