from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.secret_store import SecretStoreUnavailableError
from modules.ai_bridge import api_providers
from modules.ai_bridge.quota_tracker import QuotaTracker
from modules.ai_bridge.state_store import StateStore

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _isolated_quota_tracker(monkeypatch, tmp_path) -> QuotaTracker:
    tracker = QuotaTracker(daily_store=StateStore(db_path=tmp_path / "daily.db"))
    monkeypatch.setattr(main_module, "quota_tracker", tracker)
    return tracker


@pytest.fixture(autouse=True)
def _no_stored_key(monkeypatch):
    monkeypatch.setattr(main_module, "get_secret", lambda name: None)


# --- Gemini ------------------------------------------------------------------


def test_get_gemini_status_reports_no_key_by_default() -> None:
    response = client.get("/api/ai_bridge/gemini_api_key", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["key_configured"] is False
    assert body["requests_used_today"] == 0
    assert body["daily_limit"] == api_providers.GEMINI_RPD_LIMIT


def test_save_gemini_key_reports_key_configured(monkeypatch) -> None:
    saved = {}
    monkeypatch.setattr(main_module, "store_secret", lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(main_module, "get_secret", lambda name: saved.get(name))

    response = client.post("/api/ai_bridge/gemini_api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is True
    assert saved[api_providers.GEMINI_API_KEY_SECRET_NAME] == "my-key"


def test_save_gemini_key_rejects_an_empty_key() -> None:
    response = client.post("/api/ai_bridge/gemini_api_key", json={"api_key": ""}, headers=AUTH)

    assert response.status_code == 422


def test_save_gemini_key_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str, value: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(main_module, "store_secret", _raise)

    response = client.post("/api/ai_bridge/gemini_api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 500


def test_delete_gemini_key_reports_key_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "delete_secret", lambda name: None)

    response = client.delete("/api/ai_bridge/gemini_api_key", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is False


def test_gemini_status_reflects_daily_usage(_isolated_quota_tracker: QuotaTracker) -> None:
    _isolated_quota_tracker.record_daily_request(api_providers.GeminiApiAdapter.name)

    response = client.get("/api/ai_bridge/gemini_api_key", headers=AUTH)

    assert response.json()["requests_used_today"] == 1


def test_gemini_status_without_auth_is_rejected() -> None:
    response = client.get("/api/ai_bridge/gemini_api_key")

    assert response.status_code == 401


# --- Claude --------------------------------------------------------------


def test_get_claude_status_reports_no_key_by_default() -> None:
    response = client.get("/api/ai_bridge/claude_api_key", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is False


def test_save_claude_key_reports_key_configured(monkeypatch) -> None:
    saved = {}
    monkeypatch.setattr(main_module, "store_secret", lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(main_module, "get_secret", lambda name: saved.get(name))

    response = client.post("/api/ai_bridge/claude_api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is True
    assert saved[api_providers.CLAUDE_API_KEY_SECRET_NAME] == "my-key"


def test_save_claude_key_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str, value: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(main_module, "store_secret", _raise)

    response = client.post("/api/ai_bridge/claude_api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 500


def test_delete_claude_key_reports_key_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "delete_secret", lambda name: None)

    response = client.delete("/api/ai_bridge/claude_api_key", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is False
