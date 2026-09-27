from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, unquote, urlparse

import httpx

_EPISODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bs(?P<season>\d{1,2})[ ._-]?e(?P<episode>\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b", re.IGNORECASE),
    re.compile(
        r"season[ _/-]?(?P<season>\d{1,2})[ _/,-]*(?:episode|ep)[ _/-]?(?P<episode>\d{1,3})", re.IGNORECASE
    ),
    re.compile(
        r"(?P<season>\d{1,2})[ -]?(?:сезон|season)[ ,-]*(?P<episode>\d{1,3})[ -]?(?:серия|episode)", re.IGNORECASE
    ),
    re.compile(r"сезон[ _-]?(?P<season>\d{1,2})[ ,_-]*сери[яи][ _-]?(?P<episode>\d{1,3})", re.IGNORECASE),
)
_YEAR = re.compile(r"\((?P<paren>(?:19|20)\d{2})\)|(?<![\d])(?P<bare>19[3-9]\d|20[0-4]\d)(?![\dp])")
_SEASON_ONLY = re.compile(r"(?:season|сезон)[ _/-]?(?P<season>\d{1,2})", re.IGNORECASE)
_TITLE_NOISE = re.compile(
    r"\b(watch|online|free|full|hd|1080p|720p|4k|смотреть|онлайн|бесплатно|в хорошем качестве|netflix|hbo|"
    r"prime video|youtube|official|trailer|subtitles?|episode|season|сезон|серия|серии|shows?|series|serials?|tv|"
    r"drama|comedy|сериалы?)\b",
    re.IGNORECASE,
)
_TITLE_SEPARATORS = re.compile(r"\s+[|\-–—:]\s+")
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"})
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PAGE_FETCH_TIMEOUT_SECONDS = 10.0
_PAGE_MAX_BYTES = 256_000


@dataclass(frozen=True)
class LinkGuess:
    url: str
    series_title: str | None
    season: int | None
    episode: int | None
    youtube_id: str | None = None
    page_title: str | None = None
    kind: str | None = None
    year: int | None = None

    @property
    def is_youtube(self) -> bool:
        return self.youtube_id is not None

    @property
    def complete(self) -> bool:
        if self.kind == "movie":
            return bool(self.series_title)
        return bool(self.series_title) and self.season is not None and self.episode is not None

    @property
    def looks_like_episode(self) -> bool:
        return self.season is not None and self.episode is not None


def find_year(*texts: str) -> int | None:
    for text in texts:
        match = _YEAR.search(text or "")
        if match:
            return int(match["paren"] or match["bare"])
    return None


def youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
        return parsed.path.split("/")[2] or None
    values = parse_qs(parsed.query).get("v")
    return values[0] if values else None


def _season_episode(text: str) -> tuple[int | None, int | None, re.Match[str] | None]:
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match["season"]), int(match["episode"]), match
    season = _SEASON_ONLY.search(text)
    return (int(season["season"]) if season else None), None, None


def _clean_title(text: str) -> str | None:
    cleaned = _TITLE_NOISE.sub(" ", text)
    cleaned = re.sub(r"[\d]{3,4}p|\(\d{4}\)|\[\w+\]", " ", cleaned)
    cleaned = re.sub(r"[^\w' &.]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-&")
    return cleaned.title() if cleaned and not cleaned.isdigit() and len(cleaned) >= 2 else None


def _title_before(text: str, match: re.Match[str] | None) -> str | None:
    head = text[: match.start()] if match else text
    parts = [part for part in _TITLE_SEPARATORS.split(head) if part.strip()]
    candidate = parts[0] if parts else head
    return _clean_title(candidate)


def _slug_text(url: str) -> str:
    parsed = urlparse(url)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    return " / ".join(segment.replace("-", " ").replace("_", " ").replace(".", " ") for segment in segments)


def _title_from_slug(slug: str, match: re.Match[str] | None) -> str | None:
    segments = slug.split(" / ")
    if match is None:
        titles = [title for title in (_clean_title(segment) for segment in segments) if title]
        return titles[-1] if titles else None
    offset = 0
    for index, segment in enumerate(segments):
        end = offset + len(segment)
        if offset <= match.start() <= end:
            before = _clean_title(segment[: match.start() - offset])
            if before:
                return before
            earlier = [title for title in (_clean_title(item) for item in segments[:index]) if title]
            return earlier[-1] if earlier else None
        offset = end + len(" / ")
    return None


def parse_link(url: str, page_title: str | None = None) -> LinkGuess:
    video_id = youtube_id(url)
    title_text = html.unescape(page_title or "").strip()
    slug = _slug_text(url)
    season, episode, match = _season_episode(title_text)
    source_text = title_text
    if season is None or episode is None:
        slug_season, slug_episode, slug_match = _season_episode(slug)
        if slug_season is not None:
            season, episode, match, source_text = slug_season, slug_episode, slug_match, slug
    if source_text is slug and slug:
        series_title = _title_from_slug(slug, match)
    else:
        series_title = _title_before(source_text, match) if source_text else None
    if series_title is None and title_text:
        series_title = _title_before(title_text, None)
    if series_title is None and slug and video_id is None:
        series_title = _title_from_slug(slug, None)
    return LinkGuess(
        url=url,
        series_title=series_title,
        season=season,
        episode=episode,
        youtube_id=video_id,
        page_title=title_text or None,
        kind="series" if season is not None and episode is not None else None,
        year=find_year(title_text, slug),
    )


def fetch_page_title(url: str) -> str | None:
    try:
        with httpx.Client(timeout=_PAGE_FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            with client.stream("GET", url, headers={"User-Agent": "Mozilla/5.0 NABVE"}) as response:
                response.raise_for_status()
                collected = b""
                for chunk in response.iter_bytes():
                    collected += chunk
                    if b"</title>" in collected.lower() or len(collected) >= _PAGE_MAX_BYTES:
                        break
    except httpx.HTTPError:
        return None
    match = _TITLE_TAG.search(collected.decode("utf-8", errors="replace"))
    return html.unescape(match.group(1)).strip() if match else None


def merge(
    guess: LinkGuess,
    *,
    series_title: str | None,
    season: int | None,
    episode: int | None,
    kind: str | None = None,
    year: int | None = None,
) -> LinkGuess:
    merged_season = season if season is not None else guess.season
    merged_episode = episode if episode is not None else guess.episode
    merged_kind = kind or guess.kind
    if merged_kind is None and merged_season is not None and merged_episode is not None:
        merged_kind = "series"
    return replace(
        guess,
        series_title=series_title or guess.series_title,
        season=merged_season,
        episode=merged_episode,
        kind=merged_kind,
        year=year if year is not None else guess.year,
    )
