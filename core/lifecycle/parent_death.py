from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import sys
import threading
from typing import Callable

from core.logger import get_logger

logger = get_logger(__name__)

_PR_SET_PDEATHSIG = 1
_DEFAULT_POLL_SECONDS = 2.0


def set_parent_death_signal(signum: int = signal.SIGTERM) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        result = int(libc.prctl(_PR_SET_PDEATHSIG, ctypes.c_ulong(int(signum)), 0, 0, 0))
    except (OSError, AttributeError):
        logger.warning("prctl(PR_SET_PDEATHSIG) is unavailable", exc_info=True)
        return False
    if result != 0:
        logger.warning("prctl(PR_SET_PDEATHSIG) failed, errno=%s", ctypes.get_errno())
        return False
    return True


def terminate_self() -> None:
    if os.name == "nt":
        signal.raise_signal(signal.SIGTERM)
        return
    os.kill(os.getpid(), signal.SIGTERM)


class ParentWatcher:
    def __init__(
        self,
        expected_ppid: int,
        on_orphaned: Callable[[], None],
        interval_seconds: float = _DEFAULT_POLL_SECONDS,
    ) -> None:
        self._expected_ppid = expected_ppid
        self._on_orphaned = on_orphaned
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def parent_changed(self) -> bool:
        return os.getppid() != self._expected_ppid

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="parent-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            if self.parent_changed():
                logger.warning(
                    "Parent process %s is gone (ppid is now %s); shutting down",
                    self._expected_ppid,
                    os.getppid(),
                )
                self._on_orphaned()
                return
