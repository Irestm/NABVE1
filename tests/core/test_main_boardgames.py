from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from modules.board_games import service_layer, ui_session

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _reset_current_session():
    ui_session._current = None
    yield
    if ui_session._current is not None:
        service_layer.finish(ui_session._current)
    ui_session._current = None


def test_start_checkers_game_returns_a_board_and_legal_moves() -> None:
    response = client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "checkers"
    assert body["board_svg"].startswith("<svg")
    assert len(body["legal_moves"]) == 7
    assert body["is_over"] is False
    assert body["result"] is None


def test_start_with_unknown_kind_is_rejected() -> None:
    response = client.post("/api/boardgames/start", json={"kind": "backgammon"}, headers=AUTH)

    assert response.status_code == 400


def test_start_with_a_difficulty_is_honored_and_echoed_back() -> None:
    response = client.post(
        "/api/boardgames/start", json={"kind": "checkers", "difficulty": "very_easy"}, headers=AUTH
    )

    assert response.status_code == 200
    body = response.json()
    assert body["difficulty"] == "very_easy"


def test_start_without_a_difficulty_echoes_null() -> None:
    response = client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["difficulty"] is None


def test_start_with_unknown_difficulty_is_rejected() -> None:
    response = client.post(
        "/api/boardgames/start", json={"kind": "checkers", "difficulty": "impossible_plus"}, headers=AUTH
    )

    assert response.status_code == 400


def test_get_current_before_any_game_returns_null() -> None:
    response = client.get("/api/boardgames/current", headers=AUTH)

    assert response.status_code == 200
    assert response.json() is None


def test_get_current_after_starting_returns_the_same_state() -> None:
    client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH)

    response = client.get("/api/boardgames/current", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["kind"] == "checkers"


def test_move_without_an_active_game_is_rejected() -> None:
    response = client.post("/api/boardgames/move", json={"notation": "32-28"}, headers=AUTH)

    assert response.status_code == 409


def test_illegal_move_is_rejected() -> None:
    client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH)

    response = client.post("/api/boardgames/move", json={"notation": "not-a-real-move"}, headers=AUTH)

    assert response.status_code == 400


def test_legal_move_is_played_and_the_engine_replies() -> None:
    start = client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH).json()
    legal_move = start["legal_moves"][0]

    response = client.post("/api/boardgames/move", json={"notation": legal_move}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["last_player_move"] == legal_move
    assert body["last_engine_move"] is not None
    assert body["last_engine_move_from"] is not None
    assert body["last_engine_move_to"] is not None
    assert body["board_svg"].startswith("<svg")


def test_finish_with_no_active_game_reports_that() -> None:
    response = client.post("/api/boardgames/finish", headers=AUTH)

    assert response.status_code == 200
    assert "не была начата" in response.json()["message"]


def test_finish_ends_an_active_game_and_clears_current() -> None:
    client.post("/api/boardgames/start", json={"kind": "checkers"}, headers=AUTH)

    response = client.post("/api/boardgames/finish", headers=AUTH)

    assert response.status_code == 200
    assert ui_session.current() is None
    assert client.get("/api/boardgames/current", headers=AUTH).json() is None
