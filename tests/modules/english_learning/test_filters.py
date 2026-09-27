from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.english_learning import cefr, http_api, service_layer
from modules.english_learning.domain import Card, FilterSettings
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer
from tests.modules.english_learning.test_service_layer import SRT


def _card(episode_id: int, lemma: str, cefr_level: str | None, kind: str = "word") -> Card:
    return Card(episode_id, lemma, lemma, "MWE" if kind != "word" else "NOUN", cefr_level, ["перевод"], "x", "e", 0, "core", kind=kind)  # type: ignore[arg-type]


@pytest.fixture
def episode_id(uow_factory: Callable[[], EnglishUnitOfWork]) -> int:
    result = service_layer.import_srt_file(
        series_title="Dark",
        season=1,
        episode=1,
        raw=SRT,
        lemmatizer=FakeLemmatizer(),
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )
    assert result.episode.id is not None
    with uow_factory() as uow:
        for card in (
            _card(result.episode.id, "house", "A1"),
            _card(result.episode.id, "decide", "A2"),
            _card(result.episode.id, "honest", "B1"),
            _card(result.episode.id, "grim", "B2"),
            _card(result.episode.id, "dude", None),
            _card(result.episode.id, "break a leg", None, "idiom"),
            _card(result.episode.id, "give up", "A2", "phrasal_verb"),
        ):
            uow.cards.add(card)
        uow.commit()
    return result.episode.id


def test_default_filter_is_a2_b1_b2_and_expressions_always() -> None:
    settings = FilterSettings()

    assert settings.levels == ("A2", "B1", "B2")
    assert not settings.include_unleveled and settings.mwe_mode == "always"
    assert [settings.admits("word", level) for level in ("A1", "A2", "B1", "B2", None)] == [False, True, True, True, False]
    assert settings.admits("idiom", None) and settings.admits("idiom", "A1")


def test_follow_levels_mode_filters_expressions_too() -> None:
    settings = FilterSettings(levels=("B1",), include_unleveled=True, mwe_mode="follow_levels")

    assert settings.admits("idiom", None)
    assert not settings.admits("phrasal_verb", "A2")
    assert settings.admits("word", None)


def test_library_counts_follow_filter_and_episode_override_wins(
    uow_factory: Callable[[], EnglishUnitOfWork], episode_id: int
) -> None:
    def counts() -> tuple[int, int, str]:
        summary = service_layer.library(uow_factory)[0].episodes[0]
        return summary.words, summary.phrases, summary.display_name

    assert counts() == (3, 2, "Dark — S01E01 — 3 слова, 2 фразы")

    service_layer.save_filter("global", None, FilterSettings(("A1",), True, "follow_levels"), uow_factory)
    assert counts()[:2] == (2, 1)

    with uow_factory() as uow:
        title_id = uow.episodes.get(episode_id).title_id  # type: ignore[union-attr]
    service_layer.save_filter("title", title_id, FilterSettings(("B2",), False, "always"), uow_factory)
    assert counts()[:2] == (1, 2)

    service_layer.save_filter("episode", episode_id, FilterSettings(("A2", "B1"), False, "follow_levels"), uow_factory)
    view = service_layer.get_filter("episode", episode_id, uow_factory)
    assert view.source == "episode" and view.settings.levels == ("A2", "B1")
    assert counts()[:2] == (2, 1)

    reset = service_layer.reset_filter("episode", episode_id, uow_factory)
    assert reset.source == "title"
    assert service_layer.library(uow_factory)[0].episodes[0].has_override is False


def test_empty_filter_hides_everything(uow_factory: Callable[[], EnglishUnitOfWork], episode_id: int) -> None:
    service_layer.save_filter("global", None, FilterSettings((), False, "always"), uow_factory)

    summary = service_layer.library(uow_factory)[0].episodes[0]

    assert (summary.words, summary.phrases) == (0, 2)
    assert not FilterSettings((), False, "follow_levels").admits("idiom", None)


def test_filter_validation_drops_c_levels_and_rejects_unknown_mode(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    saved = service_layer.save_filter("global", None, FilterSettings(("B2", "C1", "A1"), False, "always"), uow_factory)

    assert saved.settings.levels == ("A1", "B2")
    with pytest.raises(ValueError):
        service_layer.save_filter("global", None, FilterSettings(("A1",), False, "weird"), uow_factory)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        service_layer.save_filter("title", None, FilterSettings(), uow_factory)


def test_module_settings_default_and_update(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    assert service_layer.get_module_settings(uow_factory) == service_layer.ModuleSettings("B1", False)

    updated = service_layer.save_module_settings(user_level="B2", allow_answer_hints=True, uow_factory=uow_factory)

    assert updated == service_layer.ModuleSettings("B2", True)
    with pytest.raises(ValueError):
        service_layer.save_module_settings(user_level="Z9", uow_factory=uow_factory)


def test_filter_and_settings_http_api(monkeypatch: pytest.MonkeyPatch, uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    for name in ("get_filter", "save_filter", "reset_filter"):
        original = getattr(service_layer, name)
        monkeypatch.setattr(service_layer, name, lambda *args, _f=original: _f(*args, uow_factory))
    get_settings = service_layer.get_module_settings
    save_settings = service_layer.save_module_settings
    monkeypatch.setattr(service_layer, "get_module_settings", lambda factory=uow_factory: get_settings(factory))
    monkeypatch.setattr(service_layer, "save_module_settings", lambda **kwargs: save_settings(**kwargs, uow_factory=uow_factory))
    app = FastAPI()
    app.include_router(http_api.router)
    client = TestClient(app)

    assert client.get("/api/english/filters/global").json() == {
        "levels": ["A2", "B1", "B2"],
        "include_unleveled": False,
        "mwe_mode": "always",
        "source": "global",
    }
    body = {"levels": ["A1"], "include_unleveled": True, "mwe_mode": "follow_levels"}
    assert client.put("/api/english/filters/global", json=body).json()["levels"] == ["A1"]
    assert client.put("/api/english/filters/global", json={**body, "levels": ["C1"]}).status_code == 422
    assert client.delete("/api/english/filters/global").status_code == 422
    assert client.put("/api/english/settings", json={"user_level": "A2"}).json() == {
        "user_level": "A2",
        "allow_answer_hints": False,
    }
