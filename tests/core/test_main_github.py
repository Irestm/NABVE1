from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.secret_store import SecretStoreUnavailableError
from modules.code_analysis import service_layer as code_analysis_service_layer

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _no_stored_pat(monkeypatch):
    monkeypatch.setattr(main_module, "get_secret", lambda name: None)


def test_get_status_reports_not_configured_by_default() -> None:
    response = client.get("/api/integrations/github_pat", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["pat_configured"] is False


def test_save_pat_reports_configured(monkeypatch) -> None:
    saved = {}
    monkeypatch.setattr(main_module, "store_secret", lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(main_module, "get_secret", lambda name: saved.get(name))

    response = client.post("/api/integrations/github_pat", json={"pat": "ghp_abc"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["pat_configured"] is True
    assert saved[code_analysis_service_layer.GITHUB_PAT_SECRET_NAME] == "ghp_abc"


def test_save_pat_rejects_empty_value() -> None:
    response = client.post("/api/integrations/github_pat", json={"pat": ""}, headers=AUTH)

    assert response.status_code == 422


def test_save_pat_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str, value: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(main_module, "store_secret", _raise)

    response = client.post("/api/integrations/github_pat", json={"pat": "ghp_abc"}, headers=AUTH)

    assert response.status_code == 500


def test_delete_pat_reports_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "delete_secret", lambda name: None)

    response = client.delete("/api/integrations/github_pat", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["pat_configured"] is False


def test_status_without_auth_is_rejected() -> None:
    response = client.get("/api/integrations/github_pat")

    assert response.status_code == 401
