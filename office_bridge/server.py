"""Standalone LibreOffice control bridge for Jarvis (NABVE1).

Runs under the SYSTEM Python (not this project's .venv) because pyuno — the
Python bridge to LibreOffice's UNO API — is a system package (python3-uno on
Ubuntu) installed into system dist-packages, not a pip-installable wheel;
the project's isolated venv can't see it. See modules/office_writer/ and
modules/office_excel/'s bridge_client.py (both point at the same host/port —
this is one shared bridge, not one per app), which spawn this script with
settings.office_bridge_system_python and talk to it over plain HTTP — same
shape and reasoning as blender_addon/server.py: stdlib http.server, no
third-party deps needed on this side of the process boundary.

One shared soffice process/UNO connection serves every app (writer_handlers,
calc_handlers, ...) rather than one soffice per app — this matches how
LibreOffice actually works (a single instance happily hosts a Writer
document and a Calc spreadsheet open at once) and avoids paying soffice's
~500MB startup cost twice. Each app's ACTIONS dispatch table uses its own
action-name vocabulary (open_document/save_document/... for Writer,
open_spreadsheet/save_spreadsheet/calc_undo/... for Calc) specifically so
they can be merged into one flat lookup here without collisions — see
_HANDLERS below.

Lifecycle: this process does NOT launch LibreOffice at import time. The
first "open_document"/"open_spreadsheet" command launches `soffice` itself
(with a UNO accept socket, no starting document — the real document comes
from loadComponentFromURL right after, so the user never sees an extra
window) and reuses that connection for every later command from any app;
nothing here assumes soffice is already running, and closing/killing
soffice just means the next open action launches it again.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import uno

import access_handlers
import calc_handlers
import impress_handlers
import writer_handlers
from office_session import OfficeCommandError, OfficeSession

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
# Purely internal loopback port soffice's UNO listener binds to — this is
# never exposed outside this bridge process, so it doesn't need to be
# configurable alongside the HTTP host/port above.
_UNO_SOCKET_PORT = 2002
_UNO_CONNECT_TIMEOUT_SECONDS = 40.0
_UNO_CONNECT_POLL_SECONDS = 0.5
# Actions that need a live Desktop before they can run at all — everything
# else assumes one of these already ran and its document is sitting in
# _session.
_OPEN_ACTIONS = frozenset({"open_document", "open_spreadsheet", "open_presentation", "open_database"})
# Disjoint by construction (see this module's docstring) — merging is safe
# without a namespacing prefix.
_HANDLERS: dict[str, Callable[[OfficeSession, dict[str, Any]], dict[str, Any]]] = {
    **writer_handlers.ACTIONS,
    **calc_handlers.ACTIONS,
    **impress_handlers.ACTIONS,
    **access_handlers.ACTIONS,
}

_session = OfficeSession()
# Serializes every UNO call through this bridge — ThreadingHTTPServer hands
# each request its own thread, but LibreOffice's UNO bridge isn't meant to
# be hammered concurrently from unrelated calls, and Jarvis only ever has
# one voice command in flight at a time anyway, so a plain lock (rather than
# Blender addon's main-thread timer-queue dance) is enough here.
_session_lock = threading.Lock()


def _log(message: str) -> None:
    print(f"[jarvis-office-bridge] {message}", file=sys.stderr, flush=True)


def _resolve_uno_context() -> Any:
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    return resolver.resolve(
        f"uno:socket,host=127.0.0.1,port={_UNO_SOCKET_PORT};urp;StarOffice.ComponentContext"
    )


def _launch_soffice() -> None:
    subprocess.Popen(
        [
            "soffice",
            "--norestore",
            "--nologo",
            f"--accept=socket,host=127.0.0.1,port={_UNO_SOCKET_PORT};urp;",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _is_desktop_alive() -> bool:
    try:
        _session.desktop.getComponents()
        return True
    except Exception:
        return False


def _ensure_desktop() -> Any:
    """Returns a connected Desktop, launching `soffice` first if nothing is
    listening on _UNO_SOCKET_PORT yet. Safe to call before every
    "open_document" — a still-live desktop from an earlier command is reused
    as-is, but only after confirming it's actually still alive: if soffice
    was closed or crashed out from under this bridge (not through Jarvis —
    e.g. the user closed the window, or it crashed), the cached reference is
    a disposed UNO proxy that raises on every call, so a stale one is
    dropped and reconnected exactly like a first-ever connection rather than
    handed back as if nothing happened."""
    if _session.desktop is not None:
        if _is_desktop_alive():
            return _session.desktop
        _log("cached LibreOffice connection is stale (soffice closed/crashed outside Jarvis), reconnecting")
        _session.ctx = None
        _session.desktop = None
        _session.writer_document = None
        _session.calc_document = None
        _session.impress_document = None
        _session.access_document = None
        _session.access_connection = None

    try:
        ctx = _resolve_uno_context()
    except Exception:
        _log("soffice not reachable yet, launching it")
        _launch_soffice()
        deadline = time.monotonic() + _UNO_CONNECT_TIMEOUT_SECONDS
        ctx = None
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            time.sleep(_UNO_CONNECT_POLL_SECONDS)
            try:
                ctx = _resolve_uno_context()
                break
            except Exception as exc:
                last_error = exc
        if ctx is None:
            raise OfficeCommandError(
                f"LibreOffice не ответил за {_UNO_CONNECT_TIMEOUT_SECONDS:.0f} секунд: {last_error}"
            ) from last_error

    desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    _session.ctx = ctx
    _session.desktop = desktop
    return desktop


class _RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib's exact signature
        _log(format % args)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "success", "message": "ok", "data": None})
        else:
            self._send_json(404, {"status": "error", "message": "Not found", "data": None})

    def do_POST(self) -> None:
        if self.path != "/command":
            self._send_json(404, {"status": "error", "message": "Not found", "data": None})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"status": "error", "message": "Malformed JSON body", "data": None})
            return

        action = payload.get("action")
        params = payload.get("params") or {}
        if not action:
            self._send_json(400, {"status": "error", "message": "Missing 'action'", "data": None})
            return

        status, message, data = self._run(action, params)
        self._send_json(200, {"status": status, "message": message, "data": data})

    def _run(self, action: str, params: dict[str, Any]) -> tuple[str, str, Any]:
        with _session_lock:
            try:
                if action in _OPEN_ACTIONS:
                    _ensure_desktop()
                handler = _HANDLERS.get(action)
                if handler is None:
                    raise OfficeCommandError(f"Неизвестное действие: {action}")
                data = handler(_session, params) or {}
                return "success", "", data
            except OfficeCommandError as exc:
                _log(f"'{action}' rejected: {exc}")
                return "error", str(exc), None
            except Exception as exc:  # raw UNO/IDL exception types land here
                _log(f"'{action}' failed: {exc}")
                return "error", str(exc), None

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _RequestHandler)
    _log(f"listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
