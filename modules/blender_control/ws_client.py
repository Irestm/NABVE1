"""Backend-side client for the Jarvis <-> Blender link.

The wire protocol is plain HTTP (see blender_addon/server.py's own docstring
for why: Blender's bundled Python has no WebSocket library out of the box,
and Jarvis only ever needs one request/one reply at a time here anyway,
which is exactly what HTTP already is). This module is still named
ws_client.py — the "remote control link to Blender" role the rest of
modules/blender_control talks to — regardless of the transport underneath.

is_blender_connected is a coroutine, not a cached bool: unlike a held-open
WebSocket, there's no persistent connection object whose live/dead state can
be read back synchronously — Blender might be closed, or the addon disabled,
between any two calls, so the only honest answer is a fresh check each time.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# Most bpy calls this backs (create/move/rotate an object, add a modifier,
# ...) finish in well under a second on Blender's main thread; this leaves
# generous headroom for a main thread that's briefly busy with something
# else (a modal operator, a UI redraw) before it drains the timer queue.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 10.0
# start_render() (see blender_addon/handlers.py) only ever has to *kick off*
# the render and return "started" - it doesn't wait for the render itself to
# finish, so this timeout only needs to cover that handshake, not the actual
# render duration. Progress is tracked separately via get_render_status.
RENDER_START_TIMEOUT_SECONDS = 15.0
HEALTH_CHECK_TIMEOUT_SECONDS = 1.5


class BlenderUnavailableError(Exception):
    """Raised by send_command() whenever the caller should report Blender as
    unreachable: the addon's server isn't listening at all (Blender not
    running, or the addon not enabled), the request failed outright, or it
    didn't reply within the timeout."""


class BlenderWsClient:
    def __init__(self, *, host: str | None = None, port: int | None = None) -> None:
        self._host = host or settings.blender_host
        self._port = port or settings.blender_port

    @property
    def _base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def is_blender_connected(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Sends one {action, params} command and waits for the addon's
        {status, message, data} reply. Raises BlenderUnavailableError for
        every failure mode (connection refused, timeout, malformed reply) —
        callers never have to distinguish "Blender is off" from "Blender
        didn't answer in time", both mean the same thing to the caller."""
        effective_timeout = timeout if timeout is not None else (
            RENDER_START_TIMEOUT_SECONDS if action == "start_render" else DEFAULT_COMMAND_TIMEOUT_SECONDS
        )
        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                response = await client.post(
                    f"{self._base_url}/command",
                    json={"action": action, "params": params or {}},
                )
        except httpx.TimeoutException as exc:
            raise BlenderUnavailableError(
                f"Blender did not respond to '{action}' within {effective_timeout}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise BlenderUnavailableError(f"Could not reach the Blender addon: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BlenderUnavailableError("Blender addon returned a non-JSON response") from exc

        if not isinstance(payload, dict) or "status" not in payload:
            raise BlenderUnavailableError("Blender addon returned an unexpected response shape")
        return payload


blender_ws_client = BlenderWsClient()
