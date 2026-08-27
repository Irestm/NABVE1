from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

# Arbitrary, deliberately unlikely to collide with a real display (:0, :1, ...)
# or another app's Xvfb instance.
_DISPLAY_NUMBER = 97
_DISPLAY = f":{_DISPLAY_NUMBER}"
_LOCK_PATH = Path(f"/tmp/.X{_DISPLAY_NUMBER}-lock")
# Xvfb's own Unix socket, separate from _LOCK_PATH above: a process killed
# hard enough (SIGKILL, a crash, or terminate() racing this same process's
# own exit without waiting — see the old stop()) can leave this behind even
# when the lock file was already cleaned up, or was never the thing that
# actually blocked a fresh bind. is_alive()-checking the lock file's owner
# PID alone isn't enough in that case — the retry in get_display() below
# also clears this.
_SOCKET_PATH = Path(f"/tmp/.X11-unix/X{_DISPLAY_NUMBER}")

_process: subprocess.Popen | None = None
_ready: str | None = None
_unavailable = False
_lock = asyncio.Lock()


def _lock_owner_pid() -> int | None:
    try:
        return int(_LOCK_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just owned by another user - can't happen for our own
        # previous backend process in practice, but "alive" is still the
        # correct answer if it somehow did.
        return True
    return True


def _find_live_xvfb_pid() -> int | None:
    """Scans /proc directly for any already-running `Xvfb :97 ...` process,
    independent of _LOCK_PATH — found live: on this environment Xvfb binds
    its socket in Linux's abstract namespace rather than a filesystem path
    at all (no /tmp/.X11-unix/X97 ever appears even for a genuinely running
    server), so a missing lock file doesn't just mean a missing *extra*
    signal, it can be the *only* signal this module had, and a plain
    SIGKILL/crash (skipping the lock file's own cleanup) made a real, still
    -bound-to-:97 orphan look dead — the exact case get_display()'s owner
    check exists for, just via a second, more direct source of truth than
    one file that isn't reliably there."""
    try:
        pid_dirs = [entry for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return None
    for pid_str in pid_dirs:
        try:
            cmdline = Path("/proc", pid_str, "cmdline").read_bytes()
        except OSError:
            continue
        args = [part.decode("utf-8", "replace") for part in cmdline.split(b"\x00") if part]
        if args and Path(args[0]).name == "Xvfb" and _DISPLAY in args[1:]:
            return int(pid_str)
    return None


async def get_display() -> str | None:
    """Starts (once per backend process) a headless Xvfb X server and
    returns its DISPLAY string, so Playwright's ai_bridge browser contexts
    can launch fully headed — real rendering, which Gemini's anti-headless
    detection requires (see providers/base.py's launch comment) — without
    ever appearing on the user's actual screen. Returns None if Xvfb isn't
    installed, so the caller can fall back to the old best-effort
    minimized-on-the-real-display behavior."""
    global _process, _ready, _unavailable
    if _ready is not None or _unavailable:
        return _ready

    async with _lock:
        if _ready is not None or _unavailable:
            return _ready

        if shutil.which("Xvfb") is None:
            logger.warning(
                "Xvfb not found on PATH; ai_bridge browser windows will use the real "
                "display instead of a hidden one. Install it with: sudo apt-get install xvfb"
            )
            _unavailable = True
            return None

        owner_pid = _lock_owner_pid()
        if owner_pid is None or not _process_is_alive(owner_pid):
            # The lock file is missing, unreadable, or points at a dead
            # PID — none of which actually proves there's no live Xvfb on
            # _DISPLAY (see _find_live_xvfb_pid's own docstring for why
            # this matters here specifically, not just in theory).
            owner_pid = _find_live_xvfb_pid()
        if owner_pid is not None and _process_is_alive(owner_pid):
            # A previous backend process's Xvfb is still running - it never
            # got to call stop() on shutdown (SIGKILL, a crash, or a plain
            # SIGTERM the old event loop didn't finish handling before the
            # process died). It's a perfectly good X server for our
            # purposes; reuse its display rather than deleting a lock that
            # isn't actually stale and then trying to bind a second Xvfb to
            # the same display number - which just fails with exit code 1
            # (the real display genuinely is in use) and silently falls back
            # to launching a REAL, visible browser window - exactly what
            # this module exists to prevent. Not tracked in `_process`
            # (stays None), so stop() below never kills a process this
            # instance didn't start.
            _ready = _DISPLAY
            logger.info(
                "Reusing existing Xvfb display %s (pid=%s) left running by an earlier process",
                _DISPLAY,
                owner_pid,
            )
            return _ready

        if _LOCK_PATH.exists():
            # Genuinely stale (owner process confirmed gone above) — Xvfb
            # refuses to bind otherwise.
            try:
                _LOCK_PATH.unlink()
            except OSError:
                logger.debug("Could not remove stale Xvfb lock at %s", _LOCK_PATH, exc_info=True)

        process = await _spawn_xvfb()
        if process is None:
            # The lock-file-owner check above already ruled out a live Xvfb
            # we should have reused instead of spawning a new one — an
            # immediate exit here means something else is blocking the
            # bind, most often a stale /tmp/.X11-unix/X97 socket left by a
            # process that died hard enough (SIGKILL, a crash, or the old
            # stop() below racing its own process's exit without waiting)
            # to skip its own cleanup, even though its lock file was
            # already gone or never pointed at a live PID in the first
            # place. One cleanup-and-retry before actually falling back to
            # a REAL visible browser window — disruptive enough (the user
            # sees it pop up mid-conversation) that it's worth a second
            # attempt rather than accepting the first failure outright.
            logger.warning(
                "Xvfb failed to bind on the first attempt; clearing stale display files and retrying once"
            )
            _clear_stale_display_files()
            process = await _spawn_xvfb()

        if process is None:
            logger.warning(
                "Xvfb still failed to bind after a retry; ai_bridge browser windows will use "
                "the real display instead of a hidden one"
            )
            _unavailable = True
            return None

        _process = process
        _ready = _DISPLAY
        logger.info("Started hidden Xvfb display %s for ai_bridge browser automation", _DISPLAY)
        return _ready


async def _spawn_xvfb() -> subprocess.Popen | None:
    """One attempt to start Xvfb on _DISPLAY and confirm it actually bound
    (still alive after a short grace period) rather than exiting right
    away (e.g. because the display is genuinely still in use). Never
    raises — get_display() decides whether a None result is worth a
    cleanup-and-retry or a final give-up."""
    process = subprocess.Popen(
        ["Xvfb", _DISPLAY, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(0.5)  # give the X server a moment to bind before anything connects
    if process.poll() is not None:
        return None
    return process


def _clear_stale_display_files() -> None:
    for path in (_LOCK_PATH, _SOCKET_PATH):
        try:
            path.unlink()
        except OSError:
            logger.debug("Could not remove stale Xvfb artifact at %s", path, exc_info=True)


def stop() -> None:
    global _process, _ready
    if _process is not None:
        _process.terminate()
        try:
            _process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            # Still alive after a graceful terminate() — waiting here
            # (rather than returning immediately, the old behavior) matters
            # because this process itself is usually about to exit right
            # after stop() returns (see core/main.py's shutdown lifespan):
            # racing that exit against Xvfb's own cleanup used to be a
            # real, observed way to leave a stale /tmp/.X11-unix/X97 socket
            # behind for the next process to trip over — see
            # _spawn_xvfb's retry above, which exists because of exactly
            # that.
            logger.warning("Xvfb pid=%s did not exit after terminate(); killing it", _process.pid)
            _process.kill()
            _process.wait(timeout=3)
        _process = None
    _ready = None
