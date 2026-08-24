from __future__ import annotations

import base64

import pytest

from modules.image_generation import api_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_params: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, params: dict, json: dict) -> _FakeResponse:
        self.last_params = params
        return self._response


def _install(monkeypatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(api_client.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


async def test_generate_image_returns_decoded_bytes(monkeypatch) -> None:
    encoded = base64.b64encode(b"fake-png-bytes").decode("ascii")
    response = _FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded}}]}}]}
    )
    _install(monkeypatch, response)

    image_bytes = await api_client.generate_image("fake-key", "a cat")

    assert image_bytes == b"fake-png-bytes"


async def test_generate_image_sends_the_key_as_a_query_param(monkeypatch) -> None:
    encoded = base64.b64encode(b"x").decode("ascii")
    response = _FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded}}]}}]}
    )
    fake_client = _install(monkeypatch, response)

    await api_client.generate_image("my-key", "a cat")

    assert fake_client.last_params == {"key": "my-key"}


async def test_generate_image_raises_on_error_response(monkeypatch) -> None:
    response = _FakeResponse(400, {"error": "bad request"})
    _install(monkeypatch, response)

    with pytest.raises(api_client.GeminiImageGenerationError):
        await api_client.generate_image("fake-key", "a cat")


async def test_generate_image_raises_when_no_candidates(monkeypatch) -> None:
    response = _FakeResponse(200, {"candidates": []})
    _install(monkeypatch, response)

    with pytest.raises(api_client.GeminiImageGenerationError):
        await api_client.generate_image("fake-key", "a cat")


async def test_generate_image_raises_when_response_has_no_image(monkeypatch) -> None:
    response = _FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "sorry, no"}]}}]})
    _install(monkeypatch, response)

    with pytest.raises(api_client.GeminiImageGenerationError):
        await api_client.generate_image("fake-key", "a cat")
