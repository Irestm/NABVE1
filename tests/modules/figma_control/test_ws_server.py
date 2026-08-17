from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import modules.figma_control.ws_server as ws_server_module
from modules.figma_control.ws_server import FigmaPluginUnavailableError, FigmaWebSocketServer


class FakeWebSocket:
    def __init__(self, token: str | None) -> None:
        self.query_params = {"token": token} if token is not None else {}
        self.sent: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None
        self._incoming: "asyncio.Queue[str | None]" = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    def push_incoming(self, data: str) -> None:
        self._incoming.put_nowait(data)

    def disconnect(self) -> None:
        self._incoming.put_nowait(None)


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    # core.config.Settings is a frozen dataclass, so its api_token field
    # can't be monkeypatched in place — patch the name ws_server.py itself
    # looks up instead (`from core.config import settings`).
    monkeypatch.setattr(ws_server_module, "settings", SimpleNamespace(api_token="secret-token"))


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0)


def test_rejects_wrong_token():
    async def scenario():
        server = FigmaWebSocketServer()
        socket = FakeWebSocket(token="wrong")
        await server.handle_connection(socket)
        assert socket.accepted is False
        assert socket.closed_code == 4401
        assert server.is_plugin_connected is False

    asyncio.run(scenario())


def test_accepts_correct_token_and_tracks_connection_state():
    async def scenario():
        server = FigmaWebSocketServer()
        socket = FakeWebSocket(token="secret-token")
        task = asyncio.create_task(server.handle_connection(socket))
        await _wait_until(lambda: server.is_plugin_connected)
        assert socket.accepted is True

        socket.disconnect()
        await task
        assert server.is_plugin_connected is False

    asyncio.run(scenario())


def test_send_command_without_connection_raises():
    async def scenario():
        server = FigmaWebSocketServer()
        with pytest.raises(FigmaPluginUnavailableError):
            await server.send_command("create_rectangle", {"width": 10, "height": 10})

    asyncio.run(scenario())


def test_send_command_round_trip_matches_request_id():
    async def scenario():
        server = FigmaWebSocketServer()
        socket = FakeWebSocket(token="secret-token")
        task = asyncio.create_task(server.handle_connection(socket))
        await _wait_until(lambda: server.is_plugin_connected)

        send_task = asyncio.create_task(server.send_command("select_layer", {"layer_name": "Кнопка"}))
        await _wait_until(lambda: len(socket.sent) == 1)

        sent_message = json.loads(socket.sent[0])
        assert sent_message["action"] == "select_layer"
        assert sent_message["params"] == {"layer_name": "Кнопка"}
        assert "request_id" in sent_message

        socket.push_incoming(
            json.dumps(
                {
                    "request_id": sent_message["request_id"],
                    "status": "success",
                    "message": "Слой выделен.",
                    "result": {"name": "Кнопка"},
                }
            )
        )

        response = await send_task
        assert response["status"] == "success"
        assert response["result"] == {"name": "Кнопка"}

        socket.disconnect()
        await task

    asyncio.run(scenario())


def test_send_command_times_out_when_no_reply():
    async def scenario():
        server = FigmaWebSocketServer(timeout_seconds=0.05)
        socket = FakeWebSocket(token="secret-token")
        task = asyncio.create_task(server.handle_connection(socket))
        await _wait_until(lambda: server.is_plugin_connected)

        with pytest.raises(FigmaPluginUnavailableError):
            await server.send_command("create_rectangle", {"width": 10, "height": 10})

        socket.disconnect()
        await task

    asyncio.run(scenario())


def test_disconnect_fails_all_pending_requests():
    async def scenario():
        server = FigmaWebSocketServer(timeout_seconds=5.0)
        socket = FakeWebSocket(token="secret-token")
        task = asyncio.create_task(server.handle_connection(socket))
        await _wait_until(lambda: server.is_plugin_connected)

        send_task = asyncio.create_task(server.send_command("undo", {}))
        await _wait_until(lambda: len(socket.sent) == 1)

        socket.disconnect()
        await task

        with pytest.raises(FigmaPluginUnavailableError):
            await send_task

    asyncio.run(scenario())
