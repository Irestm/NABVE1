from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from modules.english_learning import cefr, service_layer
from modules.english_learning.srt_parser import SrtParseError
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer

SRT = b"""1
00:00:01,000 --> 00:00:02,000
I figured it out, John.

2
00:00:03,000 --> 00:00:04,000
We decided to be honest.
"""


def _import(uow_factory: Callable[[], EnglishUnitOfWork], **overrides: object) -> service_layer.ImportResult:
    params: dict[str, object] = {
        "series_title": "Breaking Bad",
        "season": 1,
        "episode": 1,
        "raw": SRT,
        "lemmatizer": FakeLemmatizer(),
        "uow_factory": uow_factory,
        "ensure_cefr": lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    }
    params.update(overrides)
    return service_layer.import_srt_file(**params)  # type: ignore[arg-type]


def test_import_creates_series_episode_words_and_caches_srt(
    uow_factory: Callable[[], EnglishUnitOfWork], _subtitles_dir: Path
) -> None:
    result = _import(uow_factory, episode_title="Pilot")

    assert result.series.title == "Breaking Bad"
    assert result.episode.code == "S01E01"
    assert result.episode.source == "manual"
    assert {word.lemma for word in result.words} == {"figure", "decide", "honest"}
    cached = _subtitles_dir / "local_breaking_bad" / "S01E01.en.srt"
    assert cached.exists()
    assert result.episode.srt_path == str(cached)


def test_reimport_updates_the_same_episode(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    first = _import(uow_factory)
    second = _import(uow_factory, series_title="breaking bad")

    assert first.series.id == second.series.id
    assert first.episode.id == second.episode.id
    library = service_layer.library(uow_factory)
    assert len(library) == 1
    assert [(item.episode.code, item.word_count) for item in library[0].episodes] == [("S01E01", 3)]


def test_library_groups_episodes_by_series(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    _import(uow_factory, episode=2)
    _import(uow_factory, episode=1)
    _import(uow_factory, series_title="Friends")

    library = service_layer.library(uow_factory)

    assert [summary.series.title for summary in library] == ["Breaking Bad", "Friends"]
    assert [item.episode.code for item in library[0].episodes] == ["S01E01", "S01E02"]


def test_episode_words_and_missing_episode(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    result = _import(uow_factory)
    assert result.episode.id is not None

    words = service_layer.episode_words(result.episode.id, uow_factory)

    assert all(word.id is not None for word in words)
    with pytest.raises(LookupError):
        service_layer.episode_words(9999, uow_factory)


def test_invalid_input_is_rejected_before_touching_the_db(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    with pytest.raises(SrtParseError):
        _import(uow_factory, raw=b"garbage")
    with pytest.raises(ValueError):
        _import(uow_factory, series_title="   ")

    assert service_layer.library(uow_factory) == []


def test_migrations_are_idempotent(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    for _ in range(3):
        with uow_factory() as uow:
            assert uow.series.list_all() == []


def test_vtt_upload_is_converted(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    vtt = b"WEBVTT\n\n00:01.000 --> 00:02.000\nWe decided to be honest.\n"

    result = _import(uow_factory, raw=vtt)

    assert {word.lemma for word in result.words} == {"decide", "honest"}
