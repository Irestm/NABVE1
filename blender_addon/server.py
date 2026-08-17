"""Local server run inside Blender's own process by the Jarvis remote-control
addon (see __init__.py's register()/unregister()).

Plain stdlib HTTP (http.server) rather than a WebSocket server: a WebSocket
implementation needs either a third-party library (not available out of the
box in Blender's bundled Python — a user would have to pip-install into
Blender's own interpreter, which is a real installation hurdle) or a
hand-rolled protocol, for no benefit here — Jarvis's backend only ever sends
one command and waits for one reply at a time (see
modules/blender_control/ws_client.py), which is exactly what a plain
request/response HTTP call already is. http.server needs nothing beyond the
standard library, so the addon works the moment it's installed.

CRITICAL: bpy is not thread-safe. ThreadingHTTPServer handles each incoming
request on its own worker thread (never Blender's main thread), so a request
handler must never call bpy directly. Instead it schedules the actual bpy
call onto Blender's main thread via bpy.app.timers.register() — the
documented, thread-safe way for another thread to run code on Blender's main
thread — and blocks on a queue.Queue for that callback to hand back a result.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import bpy

from . import handlers

HOST = "127.0.0.1"
PORT = 8766

# How long a request-handler thread waits for the main-thread timer callback
# to actually run and hand back a result, before giving up and replying with
# an error, rather than hanging the connection forever. Generous because
# Blender's main thread may be busy (modal operators, UI redraws, ...)
# before it gets to the timer queue. start_render() is exempt from this by
# design — it schedules the render and returns immediately; the caller polls
# get_render_status() for progress instead of waiting on this timeout.
_MAIN_THREAD_TIMEOUT_SECONDS = 30.0


class _RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib's exact signature
        # BaseHTTPRequestHandler logs every request to stderr by default;
        # route it through Blender's own console output instead of silencing
        # it, so a misbehaving connection is still visible to the user.
        print("[jarvis-blender-addon] " + (format % args))

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

        status, message, data = self._run_on_main_thread(action, params)
        self._send_json(200, {"status": status, "message": message, "data": data})

    def _run_on_main_thread(self, action: str, params: dict[str, Any]) -> tuple[str, str, Any]:
        result_queue: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)
        # Set once the caller below has already given up and replied with a
        # timeout error — bpy.app.timers.register has no thread-safe way to
        # cancel run_once from here, so without this flag a Blender main
        # thread that was merely busy (not stuck) would still run run_once
        # later and silently perform the action after the caller was already
        # told it failed.
        gave_up_waiting = threading.Event()

        def run_once() -> None:
            if gave_up_waiting.is_set():
                print(f"[jarvis-blender-addon] Skipping '{action}': caller already timed out waiting for it")
                return None
            try:
                data = handlers.dispatch(action, params)
                result_queue.put((True, data))
            except Exception as exc:  # reported back over the wire, never swallowed
                print(f"[jarvis-blender-addon] '{action}' failed: {exc}")
                result_queue.put((False, str(exc)))
            return None  # returning None (vs. a float) unregisters this timer

        bpy.app.timers.register(run_once, first_interval=0.0)

        try:
            ok, data_or_message = result_queue.get(timeout=_MAIN_THREAD_TIMEOUT_SECONDS)
        except queue.Empty:
            gave_up_waiting.set()
            return (
                "error",
                f"Blender's main thread did not handle '{action}' within {_MAIN_THREAD_TIMEOUT_SECONDS}s",
                None,
            )

        if ok:
            return "success", "", data_or_message
        return "error", data_or_message, None

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None


def start(host: str = HOST, port: int = PORT) -> None:
    """Called once from __init__.py's register(). Idempotent — calling it
    again while already running is a no-op, since Blender can re-run an
    addon's register() (e.g. after a reload) without a matching unregister()
    always having happened first."""
    global _server, _server_thread
    if _server is not None:
        return
    _server = ThreadingHTTPServer((host, port), _RequestHandler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, name="jarvis-blender-addon-server", daemon=True
    )
    _server_thread.start()
    print(f"[jarvis-blender-addon] listening on http://{host}:{port}")


def stop() -> None:
    """Called from __init__.py's unregister() so disabling the addon (or
    closing Blender) doesn't leave the port bound by a dead addon."""
    global _server, _server_thread
    if _server is None:
        return
    _server.shutdown()
    _server.server_close()
    if _server_thread is not None:
        _server_thread.join(timeout=5.0)
    _server = None
    _server_thread = None
    print("[jarvis-blender-addon] stopped")
