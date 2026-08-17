from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# How long send_command() waits for the plugin to reply before treating it
# as unreachable. modules/figma_control/dispatcher.py falls back to
# screen_fallback.py the moment this fires, same as it does for "the
# plugin isn't connected at all" — a hung plugin should fail exactly the
# same way as a missing one, not hang the whole voice turn.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 5.0

WEBSOCKET_PATH = "/ws/figma_plugin"


class FigmaPluginUnavailableError(Exception):
    """Raised by send_command() whenever the caller must fall back to
    screen_fallback.py: no plugin connected, the send itself failed, or it
    didn't reply within the timeout."""


@dataclass
class _PendingRequest:
    future: "asyncio.Future[dict[str, Any]]"


class FigmaWebSocketServer:
    """Backend-side half of the Jarvis <-> Figma plugin link (see
    figma_plugin/ui.html for the other half). Holds at most one live
    connection — a single Figma Desktop instance/plugin session — and
    matches each outgoing command to its reply via a request_id, so a slow
    reply to an earlier command can never be mistaken for the answer to a
    later one.
    """

    def __init__(self, *, timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> None:
        self._socket: WebSocket | None = None
        self._pending: dict[str, _PendingRequest] = {}
        self._timeout_seconds = timeout_seconds
        self._send_lock = asyncio.Lock()

    @property
    def is_plugin_connected(self) -> bool:
        return self._socket is not None

    async def handle_connection(self, websocket: WebSocket) -> None:
        """FastAPI WebSocket endpoint body — see core/main.py's
        /ws/figma_plugin route. Rejects the handshake outright if the
        caller doesn't present this machine's api_token (same shared
        secret every other /api/* client needs — see core/config.py's
        _load_or_create_api_token docstring for why bind_host defaults to
        0.0.0.0 and this can't just be skipped)."""
        token = websocket.query_params.get("token")
        if token != settings.api_token:
            logger.warning("Rejected Figma plugin WebSocket connection: bad or missing token")
            await websocket.close(code=4401)
            return

        await websocket.accept()
        if self._socket is not None:
            logger.warning("A new Figma plugin connection replaced an existing one")
            await self._close_quietly(self._socket)
        self._socket = websocket
        logger.info("Figma plugin connected")

        try:
            while True:
                raw = await websocket.receive_text()
                self._handle_incoming(raw)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Figma plugin WebSocket connection failed")
        finally:
            if self._socket is websocket:
                self._socket = None
            self._fail_all_pending("Figma plugin disconnected")
            logger.info("Figma plugin disconnected")

    async def _close_quietly(self, websocket: WebSocket) -> None:
        try:
            await websocket.close()
        except Exception:
            logger.debug("Closing a stale Figma plugin socket raised, ignoring", exc_info=True)

    def _handle_incoming(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Figma plugin sent malformed JSON: %r", raw)
            return

        request_id = payload.get("request_id")
        pending = self._pending.pop(request_id, None) if request_id else None
        if pending is None:
            logger.warning("Figma plugin response for unknown/expired request_id=%r", request_id)
            return
        if not pending.future.done():
            pending.future.set_result(payload)

    def _fail_all_pending(self, reason: str) -> None:
        for request_id in list(self._pending):
            pending = self._pending.pop(request_id)
            if not pending.future.done():
                pending.future.set_exception(FigmaPluginUnavailableError(reason))

    async def send_command(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send one {action, params} command to the connected plugin and
        wait for its {status, message, result} reply. Raises
        FigmaPluginUnavailableError (never returns a partial/empty result)
        the moment the caller should switch to screen_fallback.py instead —
        that's every failure mode here: no connection, a send that raised,
        or a timeout."""
        async with self._send_lock:
            socket = self._socket
            if socket is None:
                raise FigmaPluginUnavailableError("Figma plugin is not connected")

            request_id = uuid.uuid4().hex
            future: "asyncio.Future[dict[str, Any]]" = asyncio.get_running_loop().create_future()
            self._pending[request_id] = _PendingRequest(future=future)

            message = {"request_id": request_id, "action": action, "params": params}
            try:
                await socket.send_text(json.dumps(message))
            except Exception as exc:
                self._pending.pop(request_id, None)
                raise FigmaPluginUnavailableError(f"Failed to send command to Figma plugin: {exc}") from exc

        try:
            return await asyncio.wait_for(future, timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise FigmaPluginUnavailableError(
                f"Figma plugin did not respond to '{action}' within {self._timeout_seconds}s"
            ) from None


figma_ws_server = FigmaWebSocketServer()
