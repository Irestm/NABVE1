from __future__ import annotations

from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def test_trigger_calls_request_manual_wake_and_reports_accepted(monkeypatch) -> None:
    monkeypatch.setattr(main_module.voice_loop, "request_manual_wake", lambda: True)

    response = client.post("/api/voice/trigger", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


def test_trigger_reports_not_accepted_when_loop_is_not_running(monkeypatch) -> None:
    monkeypatch.setattr(main_module.voice_loop, "request_manual_wake", lambda: False)

    response = client.post("/api/voice/trigger", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"accepted": False}


def test_trigger_without_auth_is_rejected() -> None:
    response = client.post("/api/voice/trigger")

    assert response.status_code == 401


def test_pause_calls_request_pause_and_reports_accepted(monkeypatch) -> None:
    monkeypatch.setattr(main_module.voice_loop, "request_pause", lambda: True)

    response = client.post("/api/voice/pause", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


def test_pause_reports_not_accepted_when_loop_is_not_running(monkeypatch) -> None:
    monkeypatch.setattr(main_module.voice_loop, "request_pause", lambda: False)

    response = client.post("/api/voice/pause", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"accepted": False}


def test_pause_without_auth_is_rejected() -> None:
    response = client.post("/api/voice/pause")

    assert response.status_code == 401
