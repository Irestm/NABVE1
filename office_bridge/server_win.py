"""Standalone Windows Office control bridge for Jarvis (NABVE1) — the
win32com counterpart of office_bridge/server.py (LibreOffice/UNO, Linux).

Runs under the SAME interpreter as the rest of the backend (pywin32 is a
pip-installable wheel, unlike pyuno on Linux — see requirements.txt's
`pywin32 ; sys_platform == 'win32'`), spawned by
modules/office_writer/bridge_client.py (and its excel/impress/access
copies), which pick this script over server.py based on platform.system() —
see those files' own comments. Speaks the identical
`{action, params} -> {status, message, data}` JSON-over-HTTP protocol as
server.py, so the backend-side bridge_client.py code needs zero changes
beyond which script/interpreter it launches.

One process serves Word+Excel+PowerPoint+Access, same as server.py serves
every LibreOffice app from one soffice connection — WinOfficeSession
(win_session.py) holds one Application object per app, created lazily on
first use and kept alive+visible across commands.

**COM apartment threading**: unlike server.py's ThreadingHTTPServer (safe
for UNO, whose calls cross a process boundary via URP rather than sharing a
COM apartment), this uses a plain single-threaded HTTPServer — every COM
call in this process must run on the one thread that called
pythoncom.CoInitialize() below. The existing comment in server.py already
notes "Jarvis only ever has one voice command in flight at a time anyway,"
so nothing is lost in practice; on Windows this is a hard COM requirement,
not just a simplification.

**Not exercised against a real Windows machine or any real MS Office
install** — there is no Windows in this development environment. Every
handler here mirrors the already-live-verified Linux/UNO logic (see
AGENT_NOTES.md) as faithfully as the two COM object models allow, with
documented deviations where Word/Excel/PowerPoint/Access genuinely work
differently (see win_writer_handlers.py/win_calc_handlers.py/
win_impress_handlers.py/win_access_handlers.py's own module docstrings) —
but it should be treated as unverified until it's actually run on Windows.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

import pythoncom
import win32com.client

import win_access_handlers
import win_calc_handlers
import win_impress_handlers
import win_writer_handlers
from win_session import OfficeCommandError, WinOfficeSession

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767

_HANDLERS: dict[str, Callable[[WinOfficeSession, dict[str, Any]], dict[str, Any]]] = {
    **win_writer_handlers.ACTIONS,
    **win_calc_handlers.ACTIONS,
    **win_impress_handlers.ACTIONS,
    **win_access_handlers.ACTIONS,
}

# Which Application object each "open_*" action needs alive before its
# handler runs — disjoint from server.py's single shared _ensure_desktop()
# since Word/Excel/PowerPoint/Access are four separate COM servers here,
# not four document types inside one shared LibreOffice desktop.
_OPEN_ACTION_APP: dict[str, str] = {
    "open_document": "word",
    "open_spreadsheet": "excel",
    "open_presentation": "powerpoint",
    "open_database": "access",
}

_session = WinOfficeSession()


def _log(message: str) -> None:
    print(f"[jarvis-office-bridge-win] {message}", file=sys.stderr, flush=True)


def _is_alive(app: Any) -> bool:
    try:
        # Any harmless property read — raises if the underlying process was
        # closed/crashed out from under this bridge (not through Jarvis).
        _ = app.Visible
        return True
    except Exception:
        return False


def _ensure_app(kind: str) -> None:
    """Idempotent, mirrors server.py's _ensure_desktop: reuses a still-live
    Application instance, or (re)creates one — covering both "never started"
    and "the user closed/crashed it outside Jarvis" the same way."""
    attr = f"{kind}_app"
    prog_id = {
        "word": "Word.Application",
        "excel": "Excel.Application",
        "powerpoint": "PowerPoint.Application",
        "access": "Access.Application",
    }[kind]

    existing = getattr(_session, attr)
    if existing is not None and _is_alive(existing):
        return
    if existing is not None:
        _log(f"{prog_id} connection is stale (closed/crashed outside Jarvis), reconnecting")
        setattr(_session, attr, None)

    app = win32com.client.Dispatch(prog_id)
    app.Visible = True
    setattr(_session, attr, app)


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
        try:
            app_kind = _OPEN_ACTION_APP.get(action)
            if app_kind is not None:
                _ensure_app(app_kind)
            handler = _HANDLERS.get(action)
            if handler is None:
                raise OfficeCommandError(f"Неизвестное действие: {action}")
            data = handler(_session, params) or {}
            return "success", "", data
        except OfficeCommandError as exc:
            _log(f"'{action}' rejected: {exc}")
            return "error", str(exc), None
        except Exception as exc:  # raw COM exception types land here
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

    # Must run on this same thread as every later COM call this process
    # makes — see this module's own docstring on apartment threading.
    pythoncom.CoInitialize()
    try:
        server = HTTPServer((args.host, args.port), _RequestHandler)
        _log(f"listening on http://{args.host}:{args.port}")
        server.serve_forever()
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
