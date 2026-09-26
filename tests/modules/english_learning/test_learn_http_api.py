from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from modules.english_learning.domain import Card, Episode, Series
from modules.english_learning.uow import EnglishUnitOfWork

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def _seed() -> tuple[int, int]:
    with EnglishUnitOfWork() as uow:
        series = Series(title="Dark")
        uow.series.add(series)
        assert series.id is not None
        episode = Episode(series_id=series.id, season=1, episode=1, source="ai_guess")
        uow.episodes.add(episode)
        assert episode.id is not None
        card_id = uow.cards.add(Card(episode.id, "decide", "decide", "VERB", "A2", ["решить"], "Choose.", "We decided.", 0, "core"))
        uow.commit()
        return episode.id, card_id


def test_learn_session_round_trip() -> None:
    episode_id, card_id = _seed()

    session = client.post(f"/api/english/episodes/{episode_id}/sessions", json={"mode": "input"}, headers=AUTH)
    assert session.status_code == 200
    session_id = session.json()["id"]
    assert session.json()["settings"]["mode"] == "input"

    wrong = client.post(
        f"/api/english/sessions/{session_id}/answers", json={"card_id": card_id, "mode": "input", "answer": "нет"}, headers=AUTH
    ).json()
    right = client.post(
        f"/api/english/sessions/{session_id}/answers", json={"card_id": card_id, "mode": "input", "answer": "Решить"}, headers=AUTH
    ).json()
    summary = client.post(f"/api/english/sessions/{session_id}/finish", headers=AUTH).json()

    assert wrong == {"correct": False, "exact": False, "matched": None, "expected": ["решить"]}
    assert right["correct"] is True
    assert summary["mistakes"] == 1
    assert summary["hard_words"][0]["card"]["word"] == "decide"


def test_learn_session_errors() -> None:
    assert client.post("/api/english/episodes/999/sessions", json={}, headers=AUTH).status_code == 404
    assert client.post("/api/english/episodes/1/sessions", json={"mode": "speed"}, headers=AUTH).status_code == 422
    assert client.post("/api/english/sessions/999/finish", headers=AUTH).status_code == 404
