from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.secret_store import SecretStoreUnavailableError
from modules.ai_bridge.state_store import StateStore
from modules.youtube_control import service_layer as youtube_service_layer
from modules.youtube_control.quota_tracker import QuotaTracker

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _isolated_quota_tracker(monkeypatch, tmp_path) -> QuotaTracker:
    tracker = QuotaTracker(store=StateStore(db_path=tmp_path / "state.db"))
    monkeypatch.setattr(youtube_service_layer, "_quota_tracker", tracker)
    return tracker


@pytest.fixture(autouse=True)
def _no_stored_key(monkeypatch):
    monkeypatch.setattr(main_module, "get_secret", lambda name: None)


def test_get_status_reports_no_key_configured_by_default() -> None:
    response = client.get("/api/youtube/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["key_configured"] is False
    assert body["units_used"] == 0
    assert body["exhausted"] is False


def test_save_api_key_reports_key_configured(monkeypatch) -> None:
    saved = {}
    monkeypatch.setattr(main_module, "store_secret", lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(main_module, "get_secret", lambda name: saved.get(name))

    response = client.post("/api/youtube/api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is True
    assert saved[youtube_service_layer.API_KEY_SECRET_NAME] == "my-key"


def test_save_api_key_rejects_an_empty_key() -> None:
    response = client.post("/api/youtube/api_key", json={"api_key": ""}, headers=AUTH)

    assert response.status_code == 422


def test_save_api_key_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str, value: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(main_module, "store_secret", _raise)

    response = client.post("/api/youtube/api_key", json={"api_key": "my-key"}, headers=AUTH)

    assert response.status_code == 500


def test_delete_api_key_reports_key_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "delete_secret", lambda name: None)

    response = client.delete("/api/youtube/api_key", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["key_configured"] is False


def test_delete_api_key_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(main_module, "delete_secret", _raise)

    response = client.delete("/api/youtube/api_key", headers=AUTH)

    assert response.status_code == 500


def test_status_reflects_quota_usage(_isolated_quota_tracker: QuotaTracker) -> None:
    _isolated_quota_tracker.record_usage(200)

    response = client.get("/api/youtube/status", headers=AUTH)

    assert response.json()["units_used"] == 200


def test_status_without_auth_is_rejected() -> None:
    response = client.get("/api/youtube/status")

    assert response.status_code == 401
