"""Backend-side client for the Jarvis <-> Writer bridge (LibreOffice Writer
on Linux, Word on Windows).

Same shape as modules/blender_control/ws_client.py (plain request/reply
HTTP, one command at a time), with one addition: unlike Blender — which the
user launches themselves, addon and all — this bridge is a process Jarvis
owns end-to-end (office_bridge/server.py on Linux, office_bridge/
server_win.py on Windows — see _IS_WINDOWS below), so
ensure_bridge_running() spawns it on demand rather than assuming it's
already up. It does NOT also guarantee LibreOffice/Word is running — that's
the bridge's own "open_document" handler's job, which launches it lazily
the first time it's needed. The wire protocol (JSON {action, params} ->
{status, message, data}) is identical on both OSes, so nothing below this
docstring branches on platform beyond picking which script/interpreter to
spawn.
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# pywin32 (win32com) is a pip wheel, installed into this project's own venv
# — unlike pyuno on Linux, no system-Python workaround is needed, so on
# Windows the bridge is spawned with this same interpreter (sys.executable)
# rather than settings.office_bridge_system_python (a Linux-only setting —
# see core/config.py's comment on it).
_IS_WINDOWS = platform.system() == "Windows"

DEFAULT_COMMAND_TIMEOUT_SECONDS = 15.0
# "open_document" may have to launch soffice cold and wait for its UNO
# listener — office_bridge/server.py's own retry loop there can take
# up to 40s, so this timeout has to stay comfortably above that or a
# slow-starting soffice looks indistinguishable from a dead bridge.
OPEN_DOCUMENT_TIMEOUT_SECONDS = 45.0
HEALTH_CHECK_TIMEOUT_SECONDS = 1.5
BRIDGE_STARTUP_TIMEOUT_SECONDS = 15.0
BRIDGE_STARTUP_POLL_SECONDS = 0.5

_BRIDGE_SCRIPT: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "office_bridge"
    / ("server_win.py" if _IS_WINDOWS else "server.py")
)


class OfficeWriterUnavailableError(Exception):
    """Raised for every failure mode a caller should report as "the Writer
    bridge/LibreOffice isn't reachable": the bridge process isn't running
    and couldn't be started, the request failed outright, or it didn't
    reply within the timeout."""


class OfficeWriterBridgeClient:
    def __init__(self, *, host: str | None = None, port: int | None = None) -> None:
        self._host = host or settings.office_bridge_host
        self._port = port or settings.office_bridge_port

    @property
    def _base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def is_bridge_running(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure_bridge_running(self) -> None:
        """Idempotent — safe to call before every command. Spawns
        office_bridge/server.py under settings.office_bridge_system_python
        (pyuno, the bridge's dependency, is a system dist-packages module,
        not installable into this project's venv) if /health doesn't already
        answer, and waits for it to come up."""
        if await self.is_bridge_running():
            return
        if not _BRIDGE_SCRIPT.exists():
            raise OfficeWriterUnavailableError(f"Файл моста LibreOffice не найден: {_BRIDGE_SCRIPT}")

        logger.info("office_writer bridge not running, launching it")
        try:
            subprocess.Popen(
                [
                    sys.executable if _IS_WINDOWS else settings.office_bridge_system_python,
                    str(_BRIDGE_SCRIPT),
                    "--host",
                    self._host,
                    "--port",
                    str(self._port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise OfficeWriterUnavailableError(f"Не удалось запустить мост LibreOffice: {exc}") from exc

        deadline = time.monotonic() + BRIDGE_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self.is_bridge_running():
                return
            await asyncio.sleep(BRIDGE_STARTUP_POLL_SECONDS)
        raise OfficeWriterUnavailableError(
            f"Мост LibreOffice Writer не поднялся за {BRIDGE_STARTUP_TIMEOUT_SECONDS:.0f} секунд"
        )

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Sends one {action, params} command and waits for the bridge's
        {status, message, data} reply. Raises OfficeWriterUnavailableError
        for every transport failure; a command the bridge understood but
        rejected (e.g. "no document open") still comes back as a normal
        {"status": "error", "message": "..."} payload — see
        modules/office_writer/dispatcher.py for how those two cases are
        told apart."""
        effective_timeout = timeout if timeout is not None else (
            OPEN_DOCUMENT_TIMEOUT_SECONDS if action == "open_document" else DEFAULT_COMMAND_TIMEOUT_SECONDS
        )
        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                response = await client.post(
                    f"{self._base_url}/command",
                    json={"action": action, "params": params or {}},
                )
        except httpx.TimeoutException as exc:
            raise OfficeWriterUnavailableError(
                f"Мост LibreOffice не ответил на '{action}' за {effective_timeout}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise OfficeWriterUnavailableError(f"Не удалось достучаться до моста LibreOffice: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OfficeWriterUnavailableError("Мост LibreOffice вернул не-JSON ответ") from exc

        if not isinstance(payload, dict) or "status" not in payload:
            raise OfficeWriterUnavailableError("Мост LibreOffice вернул ответ неожиданной формы")
        return payload


office_writer_bridge_client = OfficeWriterBridgeClient()
