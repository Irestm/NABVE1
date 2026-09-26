from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from modules.english_learning import credentials, http_api, link_import
from modules.english_learning.link_parser import LinkGuess

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def test_import_link_returns_needs_input(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[link_import.LinkImportRequest] = []

    async def fake(request: link_import.LinkImportRequest) -> link_import.NeedsInput:
        received.append(request)
        return link_import.NeedsInput(
            kind="series",
            message="choose",
            guess=LinkGuess(request.url, "The Office", 2, 5),
            options=[link_import.ShowOption(1, "The Office", 2005)],
        )

    monkeypatch.setattr(http_api.link_import, "import_from_link", fake)

    response = client.post("/api/english/import", json={"url": "https://x.tv/a", "season": 2}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_input"
    assert body["needs_input"]["options"][0]["year"] == 2005
    assert received[0].season == 2


def test_import_link_validates_body() -> None:
    assert client.post("/api/english/import", json={"url": "x"}, headers=AUTH).status_code == 422


def test_credentials_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, str] = {}
    monkeypatch.setattr(credentials, "get_secret", lambda name: store.get(name))
    monkeypatch.setattr(credentials, "store_secret", lambda name, value: store.__setitem__(name, value))
    monkeypatch.setattr(credentials, "delete_secret", lambda name: store.pop(name, None))

    first = client.put(
        "/api/english/credentials",
        json={"tmdb_api_key": " k ", "opensubtitles_api_key": "os", "opensubtitles_username": "u"},
        headers=AUTH,
    ).json()
    assert first == {"tmdb": True, "opensubtitles_api_key": True, "opensubtitles_account": False}
    assert store[credentials.TMDB_API_KEY] == "k"

    second = client.put("/api/english/credentials", json={"opensubtitles_password": "p", "tmdb_api_key": ""}, headers=AUTH).json()
    assert second == {"tmdb": False, "opensubtitles_api_key": True, "opensubtitles_account": True}
    assert client.get("/api/english/credentials", headers=AUTH).json() == second
