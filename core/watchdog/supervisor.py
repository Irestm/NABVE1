from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from types import FrameType

from core.config import BASE_DIR, settings
from core.logger import get_logger

logger = get_logger("core.watchdog.supervisor")

_DEFAULT_CHECK_INTERVAL_SECONDS = 5.0
_DEFAULT_HEALTH_TIMEOUT_SECONDS = 3.0
_DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
_DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
_DEFAULT_MAX_BACKOFF_SECONDS = 30.0
_DEFAULT_HEALTHY_RESET_SECONDS = 60.0
_TERMINATE_WAIT_SECONDS = 5.0


class Supervisor:
    def __init__(
        self,
        host: str = settings.host,
        port: int = settings.port,
        bind_host: str = settings.bind_host,
        check_interval: float = _DEFAULT_CHECK_INTERVAL_SECONDS,
        health_timeout: float = _DEFAULT_HEALTH_TIMEOUT_SECONDS,
        max_consecutive_failures: int = _DEFAULT_MAX_CONSECUTIVE_FAILURES,
        initial_backoff: float = _DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff: float = _DEFAULT_MAX_BACKOFF_SECONDS,
        healthy_reset_seconds: float = _DEFAULT_HEALTHY_RESET_SECONDS,
    ) -> None:
        # `host` is used only for the local health check (always loopback);
        # `bind_host` is what uvicorn actually binds to (0.0.0.0 by default,
        # so phones on the LAN can reach it) — see core/config.py.
        self._host = host
        self._port = port
        self._bind_host = bind_host
        self._check_interval = check_interval
        self._health_timeout = health_timeout
        self._max_consecutive_failures = max_consecutive_failures
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._healthy_reset_seconds = healthy_reset_seconds

        self._process: subprocess.Popen[bytes] | None = None
        self._stop_event = threading.Event()
        self._consecutive_failures = 0
        self._backoff = initial_backoff
        self._healthy_since: float | None = None

    @property
    def _health_url(self) -> str:
        return f"http://{self._host}:{self._port}/api/status"

    def _spawn(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "core.main:app",
            "--host",
            self._bind_host,
            "--port",
            str(self._port),
        ]
        self._process = subprocess.Popen(cmd, cwd=str(BASE_DIR))
        self._consecutive_failures = 0
        self._healthy_since = None
        logger.info("Started core process pid=%s cmd=%s", self._process.pid, " ".join(cmd))

    def _terminate(self, reason: str) -> None:
        if self._process is None:
            return
        pid = self._process.pid
        if self._process.poll() is not None:
            logger.info("Process pid=%s already exited before terminate (%s)", pid, reason)
            self._process = None
            return
        logger.warning("Terminating core process pid=%s reason=%s", pid, reason)
        self._process.terminate()
        try:
            self._process.wait(timeout=_TERMINATE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("Process pid=%s did not exit after SIGTERM, sending SIGKILL", pid)
            self._process.kill()
            self._process.wait(timeout=_TERMINATE_WAIT_SECONDS)
        self._process = None

    def _check_health(self) -> bool:
        try:
            with urllib.request.urlopen(self._health_url, timeout=self._health_timeout) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _wait_backoff(self) -> None:
        logger.info("Waiting %.1fs before restart (backoff)", self._backoff)
        self._stop_event.wait(self._backoff)
        self._backoff = min(self._backoff * 2, self._max_backoff)

    def _restart(self, reason: str) -> None:
        self._terminate(reason)
        self._wait_backoff()
        if self._stop_event.is_set():
            return
        self._spawn()

    def run(self) -> None:
        previous_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        previous_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)
        try:
            logger.info("Watchdog supervisor starting, target=%s", self._health_url)
            self._spawn()
            while not self._stop_event.is_set():
                if self._stop_event.wait(self._check_interval):
                    break

                exit_code = self._process.poll() if self._process is not None else None
                if exit_code is not None:
                    logger.error("Core process exited unexpectedly with code %s", exit_code)
                    self._restart(f"process exited with code {exit_code}")
                    continue

                if self._check_health():
                    self._consecutive_failures = 0
                    if self._healthy_since is None:
                        self._healthy_since = time.monotonic()
                    elif (
                        self._backoff != self._initial_backoff
                        and time.monotonic() - self._healthy_since >= self._healthy_reset_seconds
                    ):
                        logger.info(
                            "Core process healthy for %.0fs, resetting restart backoff",
                            self._healthy_reset_seconds,
                        )
                        self._backoff = self._initial_backoff
                else:
                    self._consecutive_failures += 1
                    self._healthy_since = None
                    logger.warning(
                        "Health check failed (%d/%d) for %s",
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                        self._health_url,
                    )
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        logger.error(
                            "Core process unresponsive after %d consecutive failed checks, treating as hang",
                            self._consecutive_failures,
                        )
                        self._restart("health check hang timeout")
        finally:
            self._terminate("supervisor shutting down")
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)
            logger.info("Watchdog supervisor stopped")

    def stop(self) -> None:
        self._stop_event.set()

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        logger.info("Received signal %s, initiating graceful shutdown", signum)
        self.stop()
