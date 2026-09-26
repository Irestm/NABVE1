from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.logger import get_logger
from modules.english_learning import cefr, subtitle_store
from modules.english_learning.domain import Card, Episode, EpisodeSource, EpisodeWord, Series
from modules.english_learning.lemmatizer import Lemmatizer, get_lemmatizer
from modules.english_learning.srt_parser import cues_to_srt, decode_srt, parse_srt, parse_vtt
from modules.english_learning.uow import EnglishUnitOfWork
from modules.english_learning.word_selection import select_words

logger = get_logger(__name__)


@dataclass(frozen=True)
class ImportResult:
    series: Series
    episode: Episode
    words: list[EpisodeWord]


def words_label(count: int) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        noun = "слов"
    elif count % 10 == 1:
        noun = "слово"
    elif 2 <= count % 10 <= 4:
        noun = "слова"
    else:
        noun = "слов"
    return f"{count} {noun}"


def folder_name(series_title: str, episode: Episode, count: int) -> str:
    return f"{series_title} — {episode.code} — {words_label(count)}"


@dataclass(frozen=True)
class EpisodeSummary:
    episode: Episode
    word_count: int
    card_count: int
    display_name: str


@dataclass(frozen=True)
class SeriesSummary:
    series: Series
    episodes: list[EpisodeSummary]


def _upsert_series(uow: EnglishUnitOfWork, title: str, imdb_id: str | None, tmdb_id: int | None) -> Series:
    series = uow.series.find(imdb_id=imdb_id, title=title)
    if series is not None:
        return series
    series = Series(title=title.strip(), imdb_id=imdb_id, tmdb_id=tmdb_id)
    uow.series.add(series)
    return series


def _upsert_episode(
    uow: EnglishUnitOfWork,
    series_id: int,
    season: int,
    episode_number: int,
    title: str | None,
    source: EpisodeSource,
    srt_path: str,
) -> Episode:
    episode = uow.episodes.find(series_id, season, episode_number)
    if episode is None:
        episode = Episode(
            series_id=series_id, season=season, episode=episode_number, title=title, source=source, srt_path=srt_path
        )
        uow.episodes.add(episode)
        return episode
    episode.title = title or episode.title
    episode.source = source
    episode.srt_path = srt_path
    uow.episodes.update(episode)
    return episode


def import_subtitles(
    *,
    series_title: str,
    season: int,
    episode: int,
    srt_text: str,
    source: EpisodeSource,
    imdb_id: str | None = None,
    tmdb_id: int | None = None,
    episode_title: str | None = None,
    lemmatizer: Lemmatizer | None = None,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    ensure_cefr: Callable[[], int] | None = None,
) -> ImportResult:
    if not series_title.strip():
        raise ValueError("Не указано название сериала")
    if season < 0 or episode < 0:
        raise ValueError("Сезон и серия не могут быть отрицательными")
    cues = parse_srt(srt_text)
    if ensure_cefr is None:
        cefr.ensure_loaded(uow_factory)
    else:
        ensure_cefr()
    lookup = cefr.load_lookup(uow_factory)
    candidates = select_words(cues, lemmatizer or get_lemmatizer(), lookup)
    variant = "ai_guess" if source == "ai_guess" else "en"
    srt_path = subtitle_store.save(imdb_id, series_title, season, episode, srt_text, variant)

    with uow_factory() as uow:
        series = _upsert_series(uow, series_title, imdb_id, tmdb_id)
        assert series.id is not None
        stored_episode = _upsert_episode(uow, series.id, season, episode, episode_title, source, str(srt_path))
        assert stored_episode.id is not None
        words = [
            EpisodeWord(
                episode_id=stored_episode.id,
                lemma=candidate.lemma,
                pos=candidate.pos,
                cefr=candidate.cefr,
                category=candidate.category,
                count=candidate.count,
                example=candidate.example,
                timestamp_ms=candidate.timestamp_ms,
                surface=candidate.surface,
            )
            for candidate in candidates
        ]
        uow.words.replace_for_episode(stored_episode.id, words)
        uow.commit()
    logger.info(
        "Imported %s %s: %d cues, %d candidate words", series.title, stored_episode.code, len(cues), len(words)
    )
    return ImportResult(series=series, episode=stored_episode, words=words)


def _as_srt(text: str) -> str:
    return cues_to_srt(parse_vtt(text)) if text.lstrip("\ufeff").startswith("WEBVTT") else text


def import_srt_file(
    *,
    series_title: str,
    season: int,
    episode: int,
    raw: bytes,
    episode_title: str | None = None,
    imdb_id: str | None = None,
    lemmatizer: Lemmatizer | None = None,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    ensure_cefr: Callable[[], int] | None = None,
) -> ImportResult:
    return import_subtitles(
        series_title=series_title,
        season=season,
        episode=episode,
        srt_text=_as_srt(decode_srt(raw)),
        source="manual",
        imdb_id=imdb_id,
        episode_title=episode_title,
        lemmatizer=lemmatizer,
        uow_factory=uow_factory,
        ensure_cefr=ensure_cefr,
    )


def stored_source(
    series_title: str,
    imdb_id: str | None,
    season: int,
    episode: int,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
) -> EpisodeSource | None:
    with uow_factory() as uow:
        series = uow.series.find(imdb_id=imdb_id, title=series_title)
        if series is None or series.id is None:
            return None
        stored = uow.episodes.find(series.id, season, episode)
        return stored.source if stored is not None else None


def _episode_summary(uow: EnglishUnitOfWork, series: Series, episode: Episode) -> EpisodeSummary:
    if episode.id is None:
        raise ValueError("Episode has no id")
    word_count = uow.words.count_for_episode(episode.id)
    card_count = uow.cards.count_for_episode(episode.id)
    return EpisodeSummary(
        episode=episode,
        word_count=word_count,
        card_count=card_count,
        display_name=folder_name(series.title, episode, card_count or word_count),
    )


def library(uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> list[SeriesSummary]:
    with uow_factory() as uow:
        result: list[SeriesSummary] = []
        for series in uow.series.list_all():
            if series.id is None:
                continue
            episodes = [_episode_summary(uow, series, episode) for episode in uow.episodes.list_for_series(series.id)]
            result.append(SeriesSummary(series=series, episodes=episodes))
        return result


def episode_words(episode_id: int, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> list[EpisodeWord]:
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        return uow.words.list_for_episode(episode_id)


def episode_cards(episode_id: int, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> list[Card]:
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        return uow.cards.list_for_episode(episode_id)


def delete_card(card_id: int, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> bool:
    with uow_factory() as uow:
        deleted = uow.cards.delete(card_id)
        uow.commit()
        return deleted
