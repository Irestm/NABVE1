from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time

from core.config import DATA_DIR
from core.logger import get_logger
from modules.gesture_control.config import CURSOR_SCALE

logger = get_logger(__name__)

# The pre-enlarge cursor size is also written here so it can be recovered if
# the backend is killed (SIGKILL / power loss) before restore() runs and the
# user is otherwise left with a permanently oversized desktop pointer.
_RECOVERY_FILE = DATA_DIR / "gesture_cursor_size.recovery"

# The enlarged cursor while gesture mode is on is the OS's *own* pointer,
# resized in place — not a separate overlay window that trails behind it
# (the user saw that as a doubled cursor). On GNOME/X11 the live pointer
# size is org.gnome.desktop.interface cursor-size, same gsettings surface
# core/os_adapter/linux.py already uses for the keyboard layout fallback.
# Elsewhere (other Linux DEs, Windows) there is no dependency-free live
# resize, so enlarge()/restore() are a logged no-op.

_GSETTINGS_SCHEMA = "org.gnome.desktop.interface"
_GSETTINGS_KEY = "cursor-size"
_MAX_CURSOR_SIZE = 128
# `gsettings set` goes through dconf over the session bus and can stall or
# silently no-op when the machine is under load. Retry, give it more room
# than a read, and only trust a write we can read back.
_SET_TIMEOUT_S = 10
_SET_ATTEMPTS = 3
# `gsettings get` prints e.g. "uint32 24" — take the trailing integer, not
# the "32" inside the type tag.
_INT_RE = re.compile(r"(\d+)\s*$")


class CursorZoom:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._original: int | None = None
        self._enlarged: int | None = None   # size set by enlarge(), for pulse()
        self._pulsing = False

    def recover_if_stale(self) -> None:
        """If a previous run left the recovery file (killed before restore),
        put the cursor size back. Safe to call at backend startup."""
        with self._lock:
            self._recover_locked()

    def _pending_recovery_size(self) -> int | None:
        """The pre-enlarge size still on disk (a marker left by a restore
        that could not write it back), or None if there's nothing valid
        pending."""
        try:
            raw = _RECOVERY_FILE.read_text().strip()
        except OSError:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if 1 <= value <= _MAX_CURSOR_SIZE else None

    def _recover_locked(self) -> None:
        try:
            raw = _RECOVERY_FILE.read_text().strip()
        except OSError:
            return
        try:
            stale = int(raw)
        except ValueError:
            _RECOVERY_FILE.unlink(missing_ok=True)
            return
        if not 1 <= stale <= _MAX_CURSOR_SIZE:
            _RECOVERY_FILE.unlink(missing_ok=True)
            return
        if self._read_gnome_cursor_size() == stale:
            _RECOVERY_FILE.unlink(missing_ok=True)
            return
        if self._write_gnome_cursor_size(stale):
            logger.info("Gesture mode: recovered cursor size to %d after an unclean exit", stale)
            _RECOVERY_FILE.unlink(missing_ok=True)
        else:
            # Leave the marker in place; a later start() / boot retries.
            logger.warning(
                "Gesture mode: could not recover cursor size to %d — keeping the marker",
                stale,
            )

    def enlarge(self) -> None:
        with self._lock:
            if self._original is not None:
                return
            self._recover_locked()  # heal a prior crash before we change anything
            # If recovery couldn't put the size back, the marker is still on
            # disk and holds the TRUE pre-enlarge size — trust that over the
            # current (still-oversized) reading, and don't overwrite it, so
            # restore() can't capture an inflated "original" and compound.
            pending = self._pending_recovery_size()
            current = pending if pending is not None else self._read_gnome_cursor_size()
            if current is None:
                return
            target = min(_MAX_CURSOR_SIZE, max(current + 1, round(current * CURSOR_SCALE)))
            if pending is None:
                try:
                    _RECOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _RECOVERY_FILE.write_text(str(current))
                except OSError:
                    logger.debug("Could not write cursor-size recovery file", exc_info=True)
            if self._write_gnome_cursor_size(target):
                self._original = current
                self._enlarged = target
                logger.info("Gesture mode: cursor size %d -> %d", current, target)
            elif pending is None:
                _RECOVERY_FILE.unlink(missing_ok=True)

    def restore(self) -> None:
        with self._lock:
            if self._original is None:
                _RECOVERY_FILE.unlink(missing_ok=True)
                return
            if self._write_gnome_cursor_size(self._original):
                logger.info("Gesture mode: cursor size restored to %d", self._original)
                self._original = None
                self._enlarged = None
                _RECOVERY_FILE.unlink(missing_ok=True)
            else:
                # Keep _original and the recovery marker so the next start()
                # (recover_if_stale) or backend boot puts the size back —
                # never drop them on a failed write, that's how the pointer
                # got stuck oversized with nothing left to heal it.
                logger.warning(
                    "Gesture mode: could not restore cursor size to %d — leaving the "
                    "recovery marker to retry on the next start / backend boot",
                    self._original,
                )

    def pulse(self, cycles: int = 3, period: float = 0.32) -> None:
        """Blink the pointer by toggling its size a few times, then leave it
        at the enlarged size. Non-blocking (runs in a short daemon thread).
        No-op unless the gesture-mode enlarge is currently in effect."""
        if self._enlarged is None or self._pulsing:
            return
        self._pulsing = True
        big = min(_MAX_CURSOR_SIZE, max(self._enlarged + 8, round(self._enlarged * 1.5)))
        base = self._enlarged

        def _run() -> None:
            try:
                for _ in range(max(1, cycles)):
                    self._write_gnome_cursor_size(big)
                    time.sleep(period / 2)
                    self._write_gnome_cursor_size(base)
                    time.sleep(period / 2)
            finally:
                # leave it at whatever enlarge()/restore() wants, not mid-blink
                self._write_gnome_cursor_size(self._enlarged or base)
                self._pulsing = False

        threading.Thread(target=_run, name="gesture-cursor-pulse", daemon=True).start()

    def _gsettings(self) -> str | None:
        if not sys.platform.startswith("linux"):
            return None
        return shutil.which("gsettings")

    def _read_gnome_cursor_size(self) -> int | None:
        tool = self._gsettings()
        if tool is None:
            return None
        try:
            result = subprocess.run(
                [tool, "get", _GSETTINGS_SCHEMA, _GSETTINGS_KEY],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.debug("gsettings get cursor-size failed", exc_info=True)
            return None
        match = _INT_RE.search(result.stdout.strip())
        return int(match.group(1)) if match else None

    def _write_gnome_cursor_size(self, size: int) -> bool:
        """Set the size and confirm it stuck. Returns True only after a
        read-back matches — a timed-out / no-op `gsettings set` under load
        must not be reported as success (that left the pointer oversized)."""
        tool = self._gsettings()
        if tool is None:
            return False
        for attempt in range(1, _SET_ATTEMPTS + 1):
            try:
                subprocess.run(
                    [tool, "set", _GSETTINGS_SCHEMA, _GSETTINGS_KEY, str(size)],
                    capture_output=True,
                    text=True,
                    timeout=_SET_TIMEOUT_S,
                    check=True,
                )
            except (subprocess.SubprocessError, OSError):
                logger.debug(
                    "gsettings set cursor-size failed (attempt %d/%d)",
                    attempt, _SET_ATTEMPTS, exc_info=True,
                )
            else:
                if self._read_gnome_cursor_size() == size:
                    return True
                logger.debug(
                    "gsettings set cursor-size %d did not stick (attempt %d/%d)",
                    size, attempt, _SET_ATTEMPTS,
                )
            if attempt < _SET_ATTEMPTS:
                time.sleep(0.2 * attempt)
        return False


cursor_zoom = CursorZoom()
