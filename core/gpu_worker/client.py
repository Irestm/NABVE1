from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from core.config import BASE_DIR
from core.gpu_worker.policy import WorkerPolicy, build_worker_env
from core.gpu_worker.protocol import (
    DISABLED_ENV,
    SHUTDOWN_OP,
    ProtocolError,
    WorkerReady,
    WorkerRequest,
    WorkerResponse,
    read_frame,
    write_frame,
)
from core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_OPERATIONS_MODULE = "core.gpu_worker.operations"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 120.0
DEFAULT_STOP_TIMEOUT_SECONDS = 3.0
_MONITOR_MAX_WAIT_SECONDS = 5.0


class GpuWorkerError(RuntimeError):
    pass


class GpuWorkerUnavailable(GpuWorkerError):
    pass


class GpuWorkerCrashed(GpuWorkerError):
    pass


class GpuWorkerTimeout(GpuWorkerError):
    pass


class GpuWorkerOperationError(GpuWorkerError):
    def __init__(self, op: str, error_type: str | None, message: str | None) -> None:
        super().__init__(f"GPU worker operation {op} failed: {error_type}: {message}")
        self.op = op
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class WorkerState:
    running: bool
    device: str | None
    pid: int | None


@dataclass
class _Handle:
    process: subprocess.Popen[bytes]
    gpu_allowed: bool
    ready: threading.Event = field(default_factory=threading.Event)
    device: str | None = None
    reader_done: bool = False


@dataclass
class _PendingCall:
    handle: _Handle
    event: threading.Event = field(default_factory=threading.Event)
    response: WorkerResponse | None = None
    failure: GpuWorkerError | None = None


class GpuWorkerClient:
    def __init__(
        self,
        policy: WorkerPolicy | None = None,
        *,
        operations_module: str = DEFAULT_OPERATIONS_MODULE,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
        stop_timeout: float = DEFAULT_STOP_TIMEOUT_SECONDS,
        python_executable: str = sys.executable,
        cwd: Path = BASE_DIR,
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        self._policy = policy or WorkerPolicy()
        self._operations_module = operations_module
        self._startup_timeout = startup_timeout
        self._stop_timeout = stop_timeout
        self._python_executable = python_executable
        self._cwd = cwd
        self._base_env = base_env
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._handle: _Handle | None = None
        self._pending: dict[int, _PendingCall] = {}
        self._next_request_id = 1
        self._in_flight = 0
        self._last_activity = time.monotonic()
        self._monitor_thread: threading.Thread | None = None
        self._closed = False
        self._spawner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu-worker-spawner")

    @property
    def policy(self) -> WorkerPolicy:
        with self._lock:
            return self._policy

    def apply_policy(self, policy: WorkerPolicy) -> None:
        with self._lock:
            if policy == self._policy:
                return
            self._policy = policy
            self._changed.notify_all()
        logger.info(
            "GPU worker policy: gpu_allowed=%s idle_timeout=%.0fs", policy.gpu_allowed, policy.idle_timeout_s
        )

    def status(self) -> WorkerState:
        with self._lock:
            handle = self._handle
            if handle is None or not handle.ready.is_set() or handle.reader_done:
                return WorkerState(running=False, device=None, pid=None)
            return WorkerState(running=True, device=handle.device, pid=handle.process.pid)

    def call(self, op: str, args: dict[str, Any], timeout: float) -> Any:
        try:
            return self._call_once(op, args, timeout)
        except GpuWorkerCrashed:
            logger.warning("GPU worker exited during %s; retrying once on a fresh worker", op, exc_info=True)
            return self._call_once(op, args, timeout)

    def call_in_background(self, op: str, args: dict[str, Any], timeout: float) -> None:
        def run() -> None:
            try:
                self.call(op, args, timeout)
            except GpuWorkerError:
                logger.warning("Background GPU worker call %s failed", op, exc_info=True)

        threading.Thread(target=run, daemon=True, name=f"gpu-worker-{op}").start()

    def stop(self) -> None:
        with self._lock:
            self._closed = True
            handle = self._handle
            self._handle = None
            self._changed.notify_all()
        if handle is not None:
            self._stop_handle(handle, "client stopped")
        self._spawner.shutdown(wait=False)

    def _call_once(self, op: str, args: dict[str, Any], timeout: float) -> Any:
        with self._lock:
            if self._closed:
                raise GpuWorkerUnavailable("GPU worker client is stopped")
            request_id = self._next_request_id
            self._next_request_id += 1
            self._in_flight += 1
            self._last_activity = time.monotonic()
        try:
            handle = self._ensure_started()
            pending = _PendingCall(handle)
            with self._lock:
                if handle.reader_done:
                    raise GpuWorkerCrashed("GPU worker exited before the request was sent")
                self._pending[request_id] = pending
            self._send(handle, WorkerRequest(request_id, op, args))
            if not pending.event.wait(timeout):
                logger.error("GPU worker call %s timed out after %.0fs; killing the worker", op, timeout)
                self._discard(handle, "call timed out")
                raise GpuWorkerTimeout(f"GPU worker call {op} timed out after {timeout:.0f}s")
            if pending.failure is not None:
                raise pending.failure
            response = pending.response
            if response is None:
                raise GpuWorkerCrashed(f"GPU worker returned no response for {op}")
            if not response.ok:
                raise GpuWorkerOperationError(op, response.error_type, response.error)
            return response.result
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
                self._in_flight -= 1
                self._last_activity = time.monotonic()
                self._changed.notify_all()

    def _send(self, handle: _Handle, request: WorkerRequest) -> None:
        stdin = handle.process.stdin
        if stdin is None:
            raise GpuWorkerCrashed("GPU worker has no input pipe")
        try:
            with self._write_lock:
                write_frame(stdin, request)
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise GpuWorkerCrashed(f"GPU worker pipe is closed: {exc}") from exc

    def _ensure_started(self) -> _Handle:
        with self._start_lock:
            with self._lock:
                if self._closed:
                    raise GpuWorkerUnavailable("GPU worker client is stopped")
                handle = self._handle
                policy = self._policy
                sole_caller = self._in_flight <= 1
            if handle is not None and not handle.reader_done:
                if handle.gpu_allowed == policy.gpu_allowed or not sole_caller:
                    return handle
                self._discard(handle, "power policy changed")
            elif handle is not None:
                self._discard(handle, "worker exited")
            return self._spawn(policy)

    def _spawn(self, policy: WorkerPolicy) -> _Handle:
        base_env = self._base_env if self._base_env is not None else os.environ
        if base_env.get(DISABLED_ENV) == "1":
            raise GpuWorkerUnavailable(f"GPU worker is disabled by {DISABLED_ENV}=1")
        env = build_worker_env(base_env, policy.gpu_allowed, os.getpid())
        command = [self._python_executable, "-m", "core.gpu_worker.server", self._operations_module]
        try:
            process = self._spawner.submit(self._popen, command, env).result()
        except (OSError, RuntimeError) as exc:
            raise GpuWorkerUnavailable(f"Could not start the GPU worker: {exc}") from exc
        handle = _Handle(process=process, gpu_allowed=policy.gpu_allowed)
        with self._lock:
            self._handle = handle
            self._last_activity = time.monotonic()
        threading.Thread(target=self._read_loop, args=(handle,), daemon=True, name="gpu-worker-reader").start()
        if not handle.ready.wait(self._startup_timeout):
            self._discard(handle, "startup timed out")
            raise GpuWorkerUnavailable(f"GPU worker did not start within {self._startup_timeout:.0f}s")
        if handle.reader_done:
            raise GpuWorkerCrashed("GPU worker exited during startup")
        logger.info(
            "GPU worker pid=%s started (device=%s, gpu_allowed=%s)", process.pid, handle.device, handle.gpu_allowed
        )
        self._ensure_monitor()
        return handle

    def _popen(self, command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=str(self._cwd),
            env=env,
        )

    def _read_loop(self, handle: _Handle) -> None:
        stream = handle.process.stdout
        try:
            while stream is not None:
                message = read_frame(stream)
                if message is None:
                    break
                if isinstance(message, WorkerReady):
                    handle.device = message.device
                    handle.ready.set()
                elif isinstance(message, WorkerResponse):
                    with self._lock:
                        pending = self._pending.get(message.request_id)
                    if pending is not None and pending.handle is handle:
                        pending.response = message
                        pending.event.set()
        except (OSError, ProtocolError, EOFError, ValueError):
            logger.warning("GPU worker pid=%s output stream broke", handle.process.pid, exc_info=True)
        finally:
            self._on_reader_exit(handle)

    def _on_reader_exit(self, handle: _Handle) -> None:
        with self._lock:
            handle.reader_done = True
            if self._handle is handle:
                self._handle = None
            orphaned = [pending for pending in self._pending.values() if pending.handle is handle]
            self._changed.notify_all()
        exit_code = self._reap(handle)
        for pending in orphaned:
            if not pending.event.is_set():
                pending.failure = GpuWorkerCrashed(f"GPU worker exited with code {exit_code} during the call")
                pending.event.set()
        handle.ready.set()
        logger.info("GPU worker pid=%s exited with code %s", handle.process.pid, exit_code)

    def _reap(self, handle: _Handle) -> int | None:
        try:
            return handle.process.wait(timeout=self._stop_timeout)
        except subprocess.TimeoutExpired:
            handle.process.kill()
            try:
                return handle.process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired:
                logger.error("GPU worker pid=%s did not exit after SIGKILL", handle.process.pid)
                return None

    def _discard(self, handle: _Handle, reason: str) -> None:
        with self._lock:
            if self._handle is handle:
                self._handle = None
        self._stop_handle(handle, reason)

    def _stop_handle(self, handle: _Handle, reason: str) -> None:
        process = handle.process
        logger.info("Stopping GPU worker pid=%s (%s)", process.pid, reason)
        if process.poll() is None:
            try:
                self._send(handle, WorkerRequest(0, SHUTDOWN_OP))
            except GpuWorkerCrashed:
                logger.debug("GPU worker pid=%s pipe already closed", process.pid, exc_info=True)
            try:
                process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=self._stop_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self._stop_timeout)
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                logger.debug("GPU worker stdin was already closed", exc_info=True)

    def _ensure_monitor(self) -> None:
        with self._lock:
            if self._monitor_thread is not None and self._monitor_thread.is_alive():
                return
            self._monitor_thread = threading.Thread(target=self._monitor, daemon=True, name="gpu-worker-idle")
            self._monitor_thread.start()

    def _monitor(self) -> None:
        while True:
            with self._lock:
                handle = self._next_idle_stop_locked()
                if handle is None:
                    if self._handle is None or self._closed:
                        self._monitor_thread = None
                        return
                    continue
                reason = "power policy changed" if handle.gpu_allowed != self._policy.gpu_allowed else "idle"
                self._handle = None
            self._stop_handle(handle, reason)

    def _next_idle_stop_locked(self) -> _Handle | None:
        handle = self._handle
        if handle is None or self._closed:
            return None
        if self._in_flight > 0:
            self._changed.wait(_MONITOR_MAX_WAIT_SECONDS)
            return None
        if handle.gpu_allowed != self._policy.gpu_allowed:
            return handle
        remaining = self._policy.idle_timeout_s - (time.monotonic() - self._last_activity)
        if remaining <= 0:
            return handle
        self._changed.wait(min(remaining, _MONITOR_MAX_WAIT_SECONDS))
        return None


_client: GpuWorkerClient | None = None
_client_lock = threading.Lock()


def get_gpu_worker_client() -> GpuWorkerClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = GpuWorkerClient()
        return _client
