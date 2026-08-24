from __future__ import annotations

from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.voice import web_pipeline

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def test_transcribe_returns_the_transcribed_text(monkeypatch) -> None:
    async def fake_transcribe(data: bytes, filename: str, language: str | None) -> str:
        assert filename == "input.webm"
        return "сделай короче"

    monkeypatch.setattr(main_module.web_pipeline, "transcribe_uploaded_audio", fake_transcribe)

    response = client.post(
        "/api/voice/transcribe",
        files={"audio": ("input.webm", b"fake-audio-bytes", "audio/webm")},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json() == {"text": "сделай короче"}


def test_transcribe_passes_the_language_form_field(monkeypatch) -> None:
    captured = {}

    async def fake_transcribe(data: bytes, filename: str, language: str | None) -> str:
        captured["language"] = language
        return "hello"

    monkeypatch.setattr(main_module.web_pipeline, "transcribe_uploaded_audio", fake_transcribe)

    client.post(
        "/api/voice/transcribe",
        files={"audio": ("input.webm", b"fake-audio-bytes", "audio/webm")},
        data={"language": "en"},
        headers=AUTH,
    )

    assert captured["language"] == "en"


def test_transcribe_returns_400_on_invalid_audio(monkeypatch) -> None:
    async def fake_transcribe(data: bytes, filename: str, language: str | None) -> str:
        raise web_pipeline.InvalidAudioError("empty audio")

    monkeypatch.setattr(main_module.web_pipeline, "transcribe_uploaded_audio", fake_transcribe)

    response = client.post(
        "/api/voice/transcribe",
        files={"audio": ("input.webm", b"", "audio/webm")},
        headers=AUTH,
    )

    assert response.status_code == 400


def test_transcribe_without_auth_is_rejected() -> None:
    response = client.post("/api/voice/transcribe", files={"audio": ("input.webm", b"x", "audio/webm")})

    assert response.status_code == 401
