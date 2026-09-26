from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from modules.english_learning import cefr, service_layer
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer
from tests.modules.english_learning.test_service_layer import SRT

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _isolated_service(monkeypatch: pytest.MonkeyPatch, uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    original_import = service_layer.import_srt_file
    original_library = service_layer.library
    original_words = service_layer.episode_words
    original_cards = service_layer.episode_cards
    original_delete = service_layer.delete_card

    def fake_import(**kwargs: object) -> service_layer.ImportResult:
        return original_import(
            **kwargs,  # type: ignore[arg-type]
            lemmatizer=FakeLemmatizer(),
            uow_factory=uow_factory,
            ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
        )

    monkeypatch.setattr(service_layer, "import_srt_file", fake_import)
    monkeypatch.setattr(service_layer, "library", lambda: original_library(uow_factory))
    monkeypatch.setattr(service_layer, "episode_words", lambda episode_id: original_words(episode_id, uow_factory))
    monkeypatch.setattr(service_layer, "episode_cards", lambda episode_id: original_cards(episode_id, uow_factory))
    monkeypatch.setattr(service_layer, "delete_card", lambda card_id: original_delete(card_id, uow_factory))


def _upload(content: bytes = SRT, **fields: str) -> object:
    data = {"series_title": "Breaking Bad", "season": "1", "episode": "3", **fields}
    return client.post(
        "/api/english/import/srt", data=data, files={"file": ("ep.srt", content, "application/x-subrip")}, headers=AUTH
    )


def test_import_then_library_and_words() -> None:
    response = _upload()

    assert response.status_code == 200  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["episode"]["code"] == "S01E03"
    assert {word["lemma"] for word in body["words"]} == {"figure", "decide", "honest"}

    library = client.get("/api/english/library", headers=AUTH).json()
    assert library["series"][0]["episodes"][0]["word_count"] == 3
    assert "CEFR-J" in library["cefr_attribution"]

    episode_id = body["episode"]["id"]
    words = client.get(f"/api/english/episodes/{episode_id}/words", headers=AUTH)
    assert words.status_code == 200
    assert len(words.json()) == 3


def test_import_rejects_non_srt() -> None:
    assert _upload(b"hello").status_code == 422  # type: ignore[attr-defined]


def test_import_rejects_negative_season() -> None:
    assert _upload(season="-1").status_code == 422  # type: ignore[attr-defined]


def test_unknown_episode_is_404() -> None:
    assert client.get("/api/english/episodes/424242/words", headers=AUTH).status_code == 404


def test_import_starts_a_job_and_cards_endpoints(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    from modules.english_learning.domain import Card

    body = _upload().json()  # type: ignore[attr-defined]
    episode_id = body["episode"]["id"]
    assert body["job"]["episode_id"] == episode_id

    with uow_factory() as uow:
        card = Card(episode_id, "figure", "figure", "VERB", "B1", ["понять"], "Understand.", "I figured it out.", 1000, "core")
        uow.cards.add(card)
        uow.commit()

    cards = client.get(f"/api/english/episodes/{episode_id}/cards", headers=AUTH)
    assert cards.status_code == 200
    assert cards.json()[0]["translations_ru"] == ["понять"]

    card_id = cards.json()[0]["id"]
    assert client.delete(f"/api/english/cards/{card_id}", headers=AUTH).status_code == 204
    assert client.delete(f"/api/english/cards/{card_id}", headers=AUTH).status_code == 404
    assert client.get("/api/english/episodes/424242/cards", headers=AUTH).status_code == 404


def test_job_endpoints() -> None:
    body = _upload().json()  # type: ignore[attr-defined]
    job_id = body["job"]["id"]

    assert client.get(f"/api/english/jobs/{job_id}", headers=AUTH).status_code == 200
    assert client.get("/api/english/jobs/99999", headers=AUTH).status_code == 404
    assert client.post("/api/english/episodes/424242/cards", headers=AUTH).status_code == 404


def test_library_has_folder_names() -> None:
    _upload()

    episode = client.get("/api/english/library", headers=AUTH).json()["series"][0]["episodes"][0]

    assert episode["display_name"] == "Breaking Bad — S01E03 — 3 слова"
