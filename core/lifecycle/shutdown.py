from __future__ import annotations

import os
import signal
import threading
import time
from typing import Callable, Sequence

from core.lifecycle.parent_death import ParentWatcher, set_parent_death_signal, terminate_self
from core.logger import get_logger

logger = get_logger(__name__)

SUPERVISED_ENV = "ASSISTANT_SUPERVISED"
SUPERVISOR_PID_ENV = "ASSISTANT_SUPERVISOR_PID"

ShutdownStep = tuple[str, Callable[[], None]]


def is_supervised() -> bool:
    return os.environ.get(SUPERVISED_ENV) == "1"


def supervisor_pid() -> int | None:
    raw = os.environ.get(SUPERVISOR_PID_ENV, "")
    return int(raw) if raw.isdigit() else None


def request_process_shutdown() -> None:
    expected_parent = supervisor_pid()
    if is_supervised():
        parent = os.getppid()
        if parent > 1 and (expected_parent is None or parent == expected_parent):
            logger.info("Shutdown requested; asking watchdog pid=%s to stop", parent)
            os.kill(parent, signal.SIGTERM)
            if os.name != "nt":
                return
    logger.info("Shutdown requested; stopping this process")
    terminate_self()


def install_supervised_child_guard() -> ParentWatcher | None:
    if not is_supervised():
        return None
    expected_parent = supervisor_pid() or os.getppid()
    set_parent_death_signal(signal.SIGTERM)
    watcher = ParentWatcher(expected_parent, terminate_self)
    if watcher.parent_changed():
        logger.warning("Watchdog pid=%s exited before startup finished; shutting down", expected_parent)
        terminate_self()
        return None
    watcher.start()
    return watcher


def run_bounded(steps: Sequence[ShutdownStep], timeout_seconds: float) -> list[str]:
    threads: list[tuple[str, threading.Thread]] = []
    for name, step in steps:
        thread = threading.Thread(target=_run_step, args=(name, step), daemon=True, name=f"shutdown-{name}")
        thread.start()
        threads.append((name, thread))

    deadline = time.monotonic() + timeout_seconds
    unfinished: list[str] = []
    for name, thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            unfinished.append(name)
    if unfinished:
        logger.warning("Shutdown steps still running after %.1fs: %s", timeout_seconds, ", ".join(unfinished))
    return unfinished


def _run_step(name: str, step: Callable[[], None]) -> None:
    try:
        step()
    except Exception:
        logger.exception("Shutdown step '%s' failed", name)
