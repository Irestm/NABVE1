from __future__ import annotations

from typing import Any

import httpx
import pytest

from modules.blender_control import ws_client as ws_client_module
from modules.blender_control.ws_client import (
    BlenderUnavailableError,
    BlenderWsClient,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    RENDER_START_TIMEOUT_SECONDS,
)


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, json_body: Any = None, json_error: bool = False) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("not json")
        return self._json_body


class _FakeAsyncClient:
    last_timeout: float | None = None
    get_response: _FakeResponse | Exception | None = None
    post_response: _FakeResponse | Exception | None = None
    last_post_url: str | None = None
    last_post_json: Any = None

    def __init__(self, *, timeout: float) -> None:
        type(self).last_timeout = timeout

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        if isinstance(type(self).get_response, Exception):
            raise type(self).get_response
        assert type(self).get_response is not None
        return type(self).get_response

    async def post(self, url: str, *, json: Any) -> _FakeResponse:
        type(self).last_post_url = url
        type(self).last_post_json = json
        if isinstance(type(self).post_response, Exception):
            raise type(self).post_response
        assert type(self).post_response is not None
        return type(self).post_response


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_client_module.httpx, "AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_is_blender_connected_true_on_200() -> None:
    _FakeAsyncClient.get_response = _FakeResponse(status_code=200)
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    assert await client.is_blender_connected() is True


@pytest.mark.asyncio
async def test_is_blender_connected_false_on_non_200() -> None:
    _FakeAsyncClient.get_response = _FakeResponse(status_code=500)
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    assert await client.is_blender_connected() is False


@pytest.mark.asyncio
async def test_is_blender_connected_false_on_http_error() -> None:
    _FakeAsyncClient.get_response = httpx.ConnectError("refused")
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    assert await client.is_blender_connected() is False


@pytest.mark.asyncio
async def test_send_command_returns_payload_on_success() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success", "message": "", "data": {"ok": True}})
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    result = await client.send_command("delete_object", {"name": "Cube"})

    assert result == {"status": "success", "message": "", "data": {"ok": True}}
    assert _FakeAsyncClient.last_post_url == "http://127.0.0.1:8766/command"
    assert _FakeAsyncClient.last_post_json == {"action": "delete_object", "params": {"name": "Cube"}}


@pytest.mark.asyncio
async def test_send_command_uses_default_timeout_for_ordinary_actions() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success"})
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    await client.send_command("delete_object", {})

    assert _FakeAsyncClient.last_timeout == DEFAULT_COMMAND_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_send_command_uses_render_timeout_for_start_render() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success"})
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    await client.send_command("start_render", {})

    assert _FakeAsyncClient.last_timeout == RENDER_START_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_send_command_respects_explicit_timeout_override() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success"})
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    await client.send_command("delete_object", {}, timeout=2.5)

    assert _FakeAsyncClient.last_timeout == 2.5


@pytest.mark.asyncio
async def test_send_command_raises_on_timeout() -> None:
    _FakeAsyncClient.post_response = httpx.TimeoutException("timed out")
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    with pytest.raises(BlenderUnavailableError):
        await client.send_command("delete_object", {})


@pytest.mark.asyncio
async def test_send_command_raises_on_http_error() -> None:
    _FakeAsyncClient.post_response = httpx.ConnectError("refused")
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    with pytest.raises(BlenderUnavailableError):
        await client.send_command("delete_object", {})


@pytest.mark.asyncio
async def test_send_command_raises_on_non_json_response() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_error=True)
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    with pytest.raises(BlenderUnavailableError):
        await client.send_command("delete_object", {})


@pytest.mark.asyncio
async def test_send_command_raises_on_unexpected_response_shape() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body=["not", "a", "dict"])
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    with pytest.raises(BlenderUnavailableError):
        await client.send_command("delete_object", {})


@pytest.mark.asyncio
async def test_send_command_raises_when_status_key_missing() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"message": "no status field"})
    client = BlenderWsClient(host="127.0.0.1", port=8766)

    with pytest.raises(BlenderUnavailableError):
        await client.send_command("delete_object", {})
