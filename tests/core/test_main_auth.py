from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import settings
from core.main import app

client = TestClient(app)


def test_api_request_without_token_is_rejected() -> None:
    response = client.get("/api/status")
    assert response.status_code == 401


def test_api_request_with_wrong_token_is_rejected() -> None:
    response = client.get("/api/status", headers={"X-Assistant-Token": "wrong"})
    assert response.status_code == 401


def test_api_request_with_correct_header_token_is_accepted() -> None:
    response = client.get("/api/status", headers={"X-Assistant-Token": settings.api_token})
    assert response.status_code == 200


def test_api_request_with_correct_query_token_is_accepted() -> None:
    # The one exception to header-only auth: an <audio> element's src (see
    # frontend/src/api/client.ts's getMeetingRecordingAudioUrl) can't attach
    # a custom header, so the token must also work as a query param.
    response = client.get("/api/status", params={"token": settings.api_token})
    assert response.status_code == 200


def test_cors_preflight_is_never_blocked_by_the_token_check() -> None:
    # Browsers never attach custom headers (or cookies, without
    # allow_credentials) to a CORS preflight OPTIONS request — if this were
    # gated the same as everything else, no cross-origin POST from the Vite
    # dev server would ever get past preflight.
    response = client.options(
        "/api/command",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
