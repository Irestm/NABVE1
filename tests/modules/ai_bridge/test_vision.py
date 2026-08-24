from __future__ import annotations

import pytest

from modules.ai_bridge import vision


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_json: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, params: dict, json: dict) -> _FakeResponse:
        self.last_json = json
        return self._response


def _install(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


async def test_analyze_image_raises_without_a_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "get_secret", lambda name: None)

    with pytest.raises(vision.VisionAnalysisError):
        await vision.analyze_image(b"fake-png", "опиши блюдо")


async def test_analyze_image_returns_the_text_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "get_secret", lambda name: "fake-key")
    response = _FakeResponse(200, payload={"candidates": [{"content": {"parts": [{"text": "Овсянка, ~350 ккал"}]}}]})
    fake_client = _install(monkeypatch, response)

    result = await vision.analyze_image(b"fake-png", "опиши блюдо")

    assert result == "Овсянка, ~350 ккал"
    encoded = fake_client.last_json["contents"][0]["parts"][1]["inline_data"]["data"]
    assert encoded  # base64 of the image bytes was embedded


async def test_analyze_image_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "get_secret", lambda name: "fake-key")
    response = _FakeResponse(500, text="server error")
    _install(monkeypatch, response)

    with pytest.raises(vision.VisionAnalysisError):
        await vision.analyze_image(b"fake-png", "опиши блюдо")


async def test_analyze_image_raises_when_no_candidates_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "get_secret", lambda name: "fake-key")
    response = _FakeResponse(200, payload={"candidates": []})
    _install(monkeypatch, response)

    with pytest.raises(vision.VisionAnalysisError):
        await vision.analyze_image(b"fake-png", "опиши блюдо")


async def test_analyze_image_raises_on_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "get_secret", lambda name: "fake-key")
    response = _FakeResponse(200, payload={"candidates": [{"content": {"parts": [{"text": ""}]}}]})
    _install(monkeypatch, response)

    with pytest.raises(vision.VisionAnalysisError):
        await vision.analyze_image(b"fake-png", "опиши блюдо")
