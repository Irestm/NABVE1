from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from core.logger import get_logger
from modules.english_learning import pipeline, subtitle_store
from modules.english_learning.domain import (
    CEFR_LEVELS,
    DEFAULT_USER_LEVEL,
    Card,
    Episode,
    EpisodeSource,
    EpisodeStats,
    EpisodeWord,
    FilterScope,
    FilterSettings,
    Title,
)
from modules.english_learning.language_filter import LanguageDetector
from modules.english_learning.lemmatizer import Lemmatizer
from modules.english_learning.movie_parts import DEFAULT_PART_MINUTES, split_parts
from modules.english_learning.srt_parser import cues_to_srt, decode_srt, parse_srt, parse_vtt
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

UowFactory = Callable[[], EnglishUnitOfWork]
USER_LEVEL_KEY = "user_level"
ALLOW_HINTS_KEY = "allow_answer_hints"


@dataclass(frozen=True)
class ImportResult:
    title: Title
    episode: Episode
    words: list[EpisodeWord]
    episodes: list[Episode] = field(default_factory=list)


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        noun = many
    elif count % 10 == 1:
        noun = one
    elif 2 <= count % 10 <= 4:
        noun = few
    else:
        noun = many
    return f"{count} {noun}"


def words_label(count: int) -> str:
    return _plural(count, "слово", "слова", "слов")


def phrases_label(count: int) -> str:
    return _plural(count, "фраза", "фразы", "фраз")


def items_label(words: int, phrases: int) -> str:
    return f"{words_label(words)}, {phrases_label(phrases)}"


def folder_name(title_name: str, episode: Episode, words: int, phrases: int = 0) -> str:
    return f"{title_name} — {episode.code} — {items_label(words, phrases)}"


def movie_folder_name(title: Title, words: int, phrases: int) -> str:
    return f"{title.display_name} — {items_label(words, phrases)}"


def part_name(episode: Episode, words: int, phrases: int) -> str:
    return f"{episode.code} — {items_label(words, phrases)}"


@dataclass(frozen=True)
class EpisodeSummary:
    episode: Episode
    word_count: int
    card_count: int
    display_name: str
    words: int = 0
    phrases: int = 0
    has_override: bool = False


@dataclass(frozen=True)
class TitleSummary:
    title: Title
    episodes: list[EpisodeSummary]
    display_name: str = ""
    words: int = 0
    phrases: int = 0
    has_override: bool = False


def _upsert_title(
    uow: EnglishUnitOfWork,
    name: str,
    imdb_id: str | None,
    tmdb_id: int | None,
    *,
    kind: str = "series",
    year: int | None = None,
) -> Title:
    title = uow.titles.find(imdb_id=imdb_id, name=name, kind=kind, year=year)
    if title is not None:
        if title.year is None and year is not None:
            title.year = year
            uow.titles.update(title)
        return title
    title = Title(name=name.strip(), kind="movie" if kind == "movie" else "series", year=year, imdb_id=imdb_id, tmdb_id=tmdb_id)
    uow.titles.add(title)
    return title


def _upsert_episode(
    uow: EnglishUnitOfWork,
    title_id: int,
    season: int,
    episode_number: int,
    title: str | None,
    source: EpisodeSource,
    srt_path: str,
) -> Episode:
    episode = uow.episodes.find(title_id, season, episode_number)
    if episode is None:
        episode = Episode(
            title_id=title_id, season=season, episode=episode_number, title=title, source=source, srt_path=srt_path
        )
        uow.episodes.add(episode)
        return episode
    episode.title = title or episode.title
    episode.source = source
    episode.srt_path = srt_path
    uow.episodes.update(episode)
    return episode


def _deps(
    lemmatizer: Lemmatizer | None, detector: LanguageDetector | None, ensure_cefr: Callable[[], int] | None
) -> pipeline.PipelineDeps:
    return pipeline.PipelineDeps(lemmatizer=lemmatizer, detector=detector, ensure_cefr=ensure_cefr)


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
    uow_factory: UowFactory = EnglishUnitOfWork,
    ensure_cefr: Callable[[], int] | None = None,
    detector: LanguageDetector | None = None,
) -> ImportResult:
    if not series_title.strip():
        raise ValueError("Не указано название сериала")
    if season < 0 or episode < 0:
        raise ValueError("Сезон и серия не могут быть отрицательными")
    cues = parse_srt(srt_text)
    variant = "ai_guess" if source == "ai_guess" else "en"
    srt_path = subtitle_store.save(imdb_id, series_title, season, episode, srt_text, variant)

    with uow_factory() as uow:
        title = _upsert_title(uow, series_title, imdb_id, tmdb_id)
        assert title.id is not None
        stored_episode = _upsert_episode(uow, title.id, season, episode, episode_title, source, str(srt_path))
        assert stored_episode.id is not None
        uow.commit()
    rebuilt = pipeline.rebuild(
        stored_episode.id, uow_factory=uow_factory, deps=_deps(lemmatizer, detector, ensure_cefr), cues=cues
    )
    words = rebuilt.words.get(stored_episode.id, [])
    logger.info("Imported %s %s: %d cues, %d candidates", title.name, stored_episode.code, len(cues), len(words))
    return ImportResult(title=title, episode=stored_episode, words=words, episodes=[stored_episode])


def import_movie(
    *,
    title_name: str,
    srt_text: str,
    source: EpisodeSource,
    year: int | None = None,
    imdb_id: str | None = None,
    tmdb_id: int | None = None,
    split: bool = True,
    part_minutes: int = DEFAULT_PART_MINUTES,
    lemmatizer: Lemmatizer | None = None,
    uow_factory: UowFactory = EnglishUnitOfWork,
    ensure_cefr: Callable[[], int] | None = None,
    detector: LanguageDetector | None = None,
) -> ImportResult:
    if not title_name.strip():
        raise ValueError("Не указано название фильма")
    cues = parse_srt(srt_text)
    variant = "ai_guess" if source == "ai_guess" else "en"
    srt_path = str(subtitle_store.save_movie(imdb_id, title_name, srt_text, variant))

    with uow_factory() as uow:
        title = _upsert_title(uow, title_name, imdb_id, tmdb_id, kind="movie", year=year)
        assert title.id is not None
        episodes = uow.episodes.list_for_title(title.id)
        if episodes:
            for stored in episodes:
                stored.source = source
                stored.srt_path = srt_path
                uow.episodes.update(stored)
        else:
            spans = split_parts(cues, part_minutes) if split else []
            if len(spans) > 1:
                for span in spans:
                    uow.episodes.add(
                        Episode(
                            title_id=title.id,
                            source=source,
                            part=span.number,
                            start_ms=span.start_ms,
                            end_ms=span.end_ms,
                            srt_path=srt_path,
                        )
                    )
            else:
                uow.episodes.add(Episode(title_id=title.id, source=source, srt_path=srt_path))
            episodes = uow.episodes.list_for_title(title.id)
        uow.commit()
    first = episodes[0]
    assert first.id is not None
    rebuilt = pipeline.rebuild(first.id, uow_factory=uow_factory, deps=_deps(lemmatizer, detector, ensure_cefr), cues=cues)
    words = [word for episode in episodes if episode.id is not None for word in rebuilt.words.get(episode.id, [])]
    logger.info("Imported movie %s: %d cues, %d parts, %d candidates", title.display_name, len(cues), len(episodes), len(words))
    return ImportResult(title=title, episode=first, words=words, episodes=episodes)


def _as_srt(text: str) -> str:
    return cues_to_srt(parse_vtt(text)) if text.lstrip("﻿").startswith("WEBVTT") else text


def import_srt_file(
    *,
    series_title: str,
    season: int | None,
    episode: int | None,
    raw: bytes,
    episode_title: str | None = None,
    imdb_id: str | None = None,
    kind: str = "series",
    year: int | None = None,
    split: bool = True,
    part_minutes: int = DEFAULT_PART_MINUTES,
    lemmatizer: Lemmatizer | None = None,
    uow_factory: UowFactory = EnglishUnitOfWork,
    ensure_cefr: Callable[[], int] | None = None,
) -> ImportResult:
    text = _as_srt(decode_srt(raw))
    if kind == "movie":
        return import_movie(
            title_name=series_title,
            srt_text=text,
            source="manual",
            year=year,
            imdb_id=imdb_id,
            split=split,
            part_minutes=part_minutes,
            lemmatizer=lemmatizer,
            uow_factory=uow_factory,
            ensure_cefr=ensure_cefr,
        )
    if season is None or episode is None:
        raise ValueError("Для серии нужны номер сезона и серии")
    return import_subtitles(
        series_title=series_title,
        season=season,
        episode=episode,
        srt_text=text,
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
    uow_factory: UowFactory = EnglishUnitOfWork,
) -> EpisodeSource | None:
    with uow_factory() as uow:
        title = uow.titles.find(imdb_id=imdb_id, name=series_title, kind="series")
        if title is None or title.id is None:
            return None
        stored = uow.episodes.find(title.id, season, episode)
        return stored.source if stored is not None else None


def stored_movie_source(title_name: str, imdb_id: str | None, uow_factory: UowFactory = EnglishUnitOfWork) -> EpisodeSource | None:
    with uow_factory() as uow:
        title = uow.titles.find(imdb_id=imdb_id, name=title_name, kind="movie")
        if title is None or title.id is None:
            return None
        episodes = uow.episodes.list_for_title(title.id)
        return episodes[0].source if episodes else None


def effective_filter(uow: EnglishUnitOfWork, title_id: int | None, episode_id: int | None) -> FilterSettings:
    if episode_id is not None and (settings := uow.filters.get("episode", episode_id)) is not None:
        return settings
    if title_id is not None and (settings := uow.filters.get("title", title_id)) is not None:
        return settings
    return uow.filters.get("global", 0) or FilterSettings()


def count_items(items: Iterable[tuple[str, str | None]], settings: FilterSettings) -> tuple[int, int]:
    words = phrases = 0
    for kind, level in items:
        if not settings.admits(kind, level):
            continue
        if kind == "word":
            words += 1
        else:
            phrases += 1
    return words, phrases


def _episode_items(uow: EnglishUnitOfWork, episode_id: int) -> list[tuple[str, str | None]]:
    cards = uow.cards.list_for_episode(episode_id)
    if cards:
        return [(card.kind, card.cefr) for card in cards]
    return [(word.kind, word.cefr) for word in uow.words.list_for_episode(episode_id)]


def _episode_summary(uow: EnglishUnitOfWork, title: Title, episode: Episode) -> EpisodeSummary:
    if episode.id is None:
        raise ValueError("Episode has no id")
    settings = effective_filter(uow, title.id, episode.id)
    words, phrases = count_items(_episode_items(uow, episode.id), settings)
    name = part_name(episode, words, phrases) if title.kind == "movie" else folder_name(title.display_name, episode, words, phrases)
    return EpisodeSummary(
        episode=episode,
        word_count=uow.words.count_for_episode(episode.id),
        card_count=uow.cards.count_for_episode(episode.id),
        display_name=name,
        words=words,
        phrases=phrases,
        has_override=uow.filters.get("episode", episode.id) is not None,
    )


def library(uow_factory: UowFactory = EnglishUnitOfWork) -> list[TitleSummary]:
    with uow_factory() as uow:
        result: list[TitleSummary] = []
        for title in uow.titles.list_all():
            if title.id is None:
                continue
            episodes = [_episode_summary(uow, title, episode) for episode in uow.episodes.list_for_title(title.id)]
            words = sum(item.words for item in episodes)
            phrases = sum(item.phrases for item in episodes)
            result.append(
                TitleSummary(
                    title=title,
                    episodes=episodes,
                    display_name=movie_folder_name(title, words, phrases) if title.kind == "movie" else title.display_name,
                    words=words,
                    phrases=phrases,
                    has_override=uow.filters.get("title", title.id) is not None,
                )
            )
        return result


def episode_words(episode_id: int, uow_factory: UowFactory = EnglishUnitOfWork) -> list[EpisodeWord]:
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        return uow.words.list_for_episode(episode_id)


def episode_cards(
    episode_id: int, uow_factory: UowFactory = EnglishUnitOfWork, *, include_archived: bool = False
) -> list[Card]:
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        return uow.cards.list_for_episode(episode_id, include_archived=include_archived)


def delete_card(card_id: int, uow_factory: UowFactory = EnglishUnitOfWork) -> bool:
    with uow_factory() as uow:
        deleted = uow.cards.delete(card_id)
        uow.commit()
        return deleted


def episode_stats(episode_id: int, uow_factory: UowFactory = EnglishUnitOfWork) -> EpisodeStats | None:
    with uow_factory() as uow:
        return uow.stats.get(episode_id)


def _validate_filter(settings: FilterSettings) -> FilterSettings:
    levels = tuple(level for level in CEFR_LEVELS if level in settings.levels and level in ("A1", "A2", "B1", "B2"))
    if settings.mwe_mode not in ("follow_levels", "always"):
        raise ValueError("Неизвестный режим выражений")
    return FilterSettings(levels=levels, include_unleveled=settings.include_unleveled, mwe_mode=settings.mwe_mode)


def _scope_id(scope: FilterScope, scope_id: int | None) -> int:
    if scope == "global":
        return 0
    if scope_id is None:
        raise ValueError("Для переопределения нужен id тайтла или эпизода")
    return scope_id


@dataclass(frozen=True)
class FilterView:
    settings: FilterSettings
    source: FilterScope


def get_filter(
    scope: FilterScope, scope_id: int | None = None, uow_factory: UowFactory = EnglishUnitOfWork
) -> FilterView:
    with uow_factory() as uow:
        if scope == "episode" and scope_id is not None:
            episode = uow.episodes.get(scope_id)
            if episode is None:
                raise LookupError(f"Эпизод {scope_id} не найден")
            if (own := uow.filters.get("episode", scope_id)) is not None:
                return FilterView(own, "episode")
            if (title_level := uow.filters.get("title", episode.title_id)) is not None:
                return FilterView(title_level, "title")
        elif scope == "title" and scope_id is not None:
            if (own := uow.filters.get("title", scope_id)) is not None:
                return FilterView(own, "title")
        return FilterView(uow.filters.get("global", 0) or FilterSettings(), "global")


def save_filter(
    scope: FilterScope, scope_id: int | None, settings: FilterSettings, uow_factory: UowFactory = EnglishUnitOfWork
) -> FilterView:
    validated = _validate_filter(settings)
    with uow_factory() as uow:
        uow.filters.save(scope, _scope_id(scope, scope_id), validated)
        uow.commit()
    return FilterView(validated, scope)


def reset_filter(scope: FilterScope, scope_id: int | None, uow_factory: UowFactory = EnglishUnitOfWork) -> FilterView:
    if scope == "global":
        raise ValueError("Глобальные настройки не сбрасываются — только переопределения")
    with uow_factory() as uow:
        uow.filters.delete(scope, _scope_id(scope, scope_id))
        uow.commit()
    return get_filter(scope, scope_id, uow_factory)


@dataclass(frozen=True)
class ModuleSettings:
    user_level: str
    allow_answer_hints: bool


def get_module_settings(uow_factory: UowFactory = EnglishUnitOfWork) -> ModuleSettings:
    with uow_factory() as uow:
        level = uow.settings.get(USER_LEVEL_KEY)
        hints = uow.settings.get(ALLOW_HINTS_KEY)
    return ModuleSettings(
        user_level=level if level in CEFR_LEVELS else DEFAULT_USER_LEVEL,
        allow_answer_hints=bool(hints),
    )


def save_module_settings(
    *, user_level: str | None = None, allow_answer_hints: bool | None = None, uow_factory: UowFactory = EnglishUnitOfWork
) -> ModuleSettings:
    if user_level is not None and user_level not in CEFR_LEVELS:
        raise ValueError("Уровень должен быть от A1 до C2")
    with uow_factory() as uow:
        if user_level is not None:
            uow.settings.set(USER_LEVEL_KEY, user_level)
        if allow_answer_hints is not None:
            uow.settings.set(ALLOW_HINTS_KEY, allow_answer_hints)
        uow.commit()
    return get_module_settings(uow_factory)
