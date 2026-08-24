from __future__ import annotations

from typing import Any

import httpx
import pytest

from modules.office_access import bridge_client as bridge_client_module
from modules.office_access.bridge_client import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    OfficeAccessBridgeClient,
    OfficeAccessUnavailableError,
    OPEN_DATABASE_TIMEOUT_SECONDS,
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


class _FakeScriptPath:
    """Path.exists() is unpatchable per-instance (pathlib slots out
    arbitrary attributes), so ensure_bridge_running tests swap out the whole
    _BRIDGE_SCRIPT module attribute for one of these instead."""

    def __init__(self, *, exists: bool) -> None:
        self._exists = exists

    def exists(self) -> bool:
        return self._exists

    def __str__(self) -> str:
        return "/fake/office_bridge/server.py"


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_client_module.httpx, "AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_is_bridge_running_true_on_200() -> None:
    _FakeAsyncClient.get_response = _FakeResponse(status_code=200)
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    assert await client.is_bridge_running() is True


@pytest.mark.asyncio
async def test_is_bridge_running_false_on_non_200() -> None:
    _FakeAsyncClient.get_response = _FakeResponse(status_code=500)
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    assert await client.is_bridge_running() is False


@pytest.mark.asyncio
async def test_is_bridge_running_false_on_http_error() -> None:
    _FakeAsyncClient.get_response = httpx.ConnectError("refused")
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    assert await client.is_bridge_running() is False


@pytest.mark.asyncio
async def test_ensure_bridge_running_skips_spawn_when_already_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.get_response = _FakeResponse(status_code=200)
    spawned = False

    def fake_popen(*args: Any, **kwargs: Any) -> None:
        nonlocal spawned
        spawned = True

    monkeypatch.setattr(bridge_client_module.subprocess, "Popen", fake_popen)
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    await client.ensure_bridge_running()

    assert spawned is False


@pytest.mark.asyncio
async def test_ensure_bridge_running_spawns_and_waits_for_health(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            httpx.ConnectError("refused"),  # initial check: not up yet
            httpx.ConnectError("refused"),  # first poll after spawning
            _FakeResponse(status_code=200),  # second poll: up
        ]
    )

    class _SequencedClient(_FakeAsyncClient):
        async def get(self, url: str) -> _FakeResponse:
            next_response = next(responses)
            if isinstance(next_response, Exception):
                raise next_response
            return next_response

    monkeypatch.setattr(bridge_client_module.httpx, "AsyncClient", _SequencedClient)
    monkeypatch.setattr(bridge_client_module.asyncio, "sleep", _no_sleep)

    spawn_args: list[Any] = []

    def fake_popen(args: list[str], **kwargs: Any) -> None:
        spawn_args.append(args)

    monkeypatch.setattr(bridge_client_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bridge_client_module, "_BRIDGE_SCRIPT", _FakeScriptPath(exists=True))

    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)
    await client.ensure_bridge_running()

    assert len(spawn_args) == 1
    assert "--host" in spawn_args[0]
    assert "--port" in spawn_args[0]


@pytest.mark.asyncio
async def test_ensure_bridge_running_raises_when_script_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.get_response = httpx.ConnectError("refused")
    monkeypatch.setattr(bridge_client_module, "_BRIDGE_SCRIPT", _FakeScriptPath(exists=False))
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.ensure_bridge_running()


@pytest.mark.asyncio
async def test_ensure_bridge_running_raises_when_never_comes_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.get_response = httpx.ConnectError("refused")
    monkeypatch.setattr(bridge_client_module.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(bridge_client_module, "_BRIDGE_SCRIPT", _FakeScriptPath(exists=True))
    monkeypatch.setattr(bridge_client_module.asyncio, "sleep", _no_sleep)
    # A negative timeout puts the deadline in the past relative to
    # time.monotonic() right away, so the poll loop exits on its first
    # check instead of actually waiting BRIDGE_STARTUP_TIMEOUT_SECONDS.
    monkeypatch.setattr(bridge_client_module, "BRIDGE_STARTUP_TIMEOUT_SECONDS", -1.0)

    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.ensure_bridge_running()


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_ensure_bridge_running_spawns_server_win_with_this_interpreter_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # See modules/office_writer/test_bridge_client.py's identical test for
    # why _IS_WINDOWS/_BRIDGE_SCRIPT are patched directly rather than via
    # platform.system() (computed once at import time, not per-call).
    import sys

    responses = iter(
        [
            httpx.ConnectError("refused"),
            _FakeResponse(status_code=200),
        ]
    )

    class _SequencedClient(_FakeAsyncClient):
        async def get(self, url: str) -> _FakeResponse:
            next_response = next(responses)
            if isinstance(next_response, Exception):
                raise next_response
            return next_response

    monkeypatch.setattr(bridge_client_module.httpx, "AsyncClient", _SequencedClient)
    monkeypatch.setattr(bridge_client_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(bridge_client_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(bridge_client_module, "_BRIDGE_SCRIPT", _FakeScriptPath(exists=True))
    spawn_args: list[Any] = []

    def fake_popen(args: Any, **kwargs: Any) -> None:
        spawn_args.append(args)

    monkeypatch.setattr(bridge_client_module.subprocess, "Popen", fake_popen)
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    await client.ensure_bridge_running()

    assert spawn_args[0][0] == sys.executable


@pytest.mark.asyncio
async def test_send_command_returns_payload_on_success() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success", "message": "", "data": {}})
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    result = await client.send_command("list_tables", {})

    assert result == {"status": "success", "message": "", "data": {}}
    assert _FakeAsyncClient.last_post_url == "http://127.0.0.1:8767/command"
    assert _FakeAsyncClient.last_post_json == {"action": "list_tables", "params": {}}


@pytest.mark.asyncio
async def test_send_command_uses_default_timeout_for_ordinary_actions() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success"})
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    await client.send_command("list_tables", {})

    assert _FakeAsyncClient.last_timeout == DEFAULT_COMMAND_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_send_command_uses_longer_timeout_for_open_database() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"status": "success"})
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    await client.send_command("open_database", {})

    assert _FakeAsyncClient.last_timeout == OPEN_DATABASE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_send_command_raises_on_timeout() -> None:
    _FakeAsyncClient.post_response = httpx.TimeoutException("timed out")
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.send_command("list_tables", {})


@pytest.mark.asyncio
async def test_send_command_raises_on_http_error() -> None:
    _FakeAsyncClient.post_response = httpx.ConnectError("refused")
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.send_command("list_tables", {})


@pytest.mark.asyncio
async def test_send_command_raises_on_non_json_response() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_error=True)
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.send_command("list_tables", {})


@pytest.mark.asyncio
async def test_send_command_raises_when_status_key_missing() -> None:
    _FakeAsyncClient.post_response = _FakeResponse(json_body={"message": "no status field"})
    client = OfficeAccessBridgeClient(host="127.0.0.1", port=8767)

    with pytest.raises(OfficeAccessUnavailableError):
        await client.send_command("list_tables", {})
