from __future__ import annotations

import asyncio
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

_process: subprocess.Popen | None = None
_ready: str | None = None
_unavailable = False
_lock = asyncio.Lock()


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

        if _LOCK_PATH.exists():
            # Stale lock from a previous crashed run — Xvfb refuses to bind otherwise.
            try:
                _LOCK_PATH.unlink()
            except OSError:
                logger.debug("Could not remove stale Xvfb lock at %s", _LOCK_PATH, exc_info=True)

        process = subprocess.Popen(
            ["Xvfb", _DISPLAY, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)  # give the X server a moment to bind before anything connects
        if process.poll() is not None:
            logger.warning(
                "Xvfb exited immediately (code %s); ai_bridge browser windows will use "
                "the real display instead of a hidden one",
                process.returncode,
            )
            _unavailable = True
            return None

        _process = process
        _ready = _DISPLAY
        logger.info("Started hidden Xvfb display %s for ai_bridge browser automation", _DISPLAY)
        return _ready


def stop() -> None:
    global _process, _ready
    if _process is not None:
        _process.terminate()
        _process = None
    _ready = None
