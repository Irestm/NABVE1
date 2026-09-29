from __future__ import annotations

import importlib
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any, BinaryIO, Callable

from core.gpu_worker.context import WorkerContext
from core.gpu_worker.protocol import (
    GPU_ALLOWED_ENV,
    PARENT_PID_ENV,
    SHUTDOWN_OP,
    WorkerReady,
    WorkerRequest,
    WorkerResponse,
    read_frame,
    write_frame,
)
from core.lifecycle.parent_death import ParentWatcher, set_parent_death_signal

logger = logging.getLogger("core.gpu_worker.server")

Operation = Callable[[WorkerContext, dict[str, Any]], Any]

MAX_CONCURRENT_OPERATIONS = 4


class _ResponseWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, message: object) -> None:
        with self._lock:
            try:
                write_frame(self._stream, message)
            except (BrokenPipeError, OSError):
                logger.warning("GPU worker lost its parent pipe; exiting", exc_info=True)
                os._exit(0)


def _claim_protocol_streams() -> tuple[BinaryIO, BinaryIO]:
    protocol_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    protocol_in = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
    return protocol_in, protocol_out


def _guard_parent() -> bool:
    raw_parent = os.environ.get(PARENT_PID_ENV, "")
    if not raw_parent.isdigit():
        return True
    parent = int(raw_parent)
    set_parent_death_signal(signal.SIGTERM)
    if os.getppid() != parent:
        return False
    ParentWatcher(parent, lambda: os._exit(0), interval_seconds=1.0).start()
    return True


def _execute(
    operations: dict[str, Operation],
    context: WorkerContext,
    request: WorkerRequest,
    writer: _ResponseWriter,
) -> None:
    operation = operations.get(request.op)
    if operation is None:
        writer.send(
            WorkerResponse(request.request_id, ok=False, error=f"Unknown operation {request.op!r}", error_type="KeyError")
        )
        return
    try:
        result = operation(context, request.args)
    except BaseException as exc:
        logger.exception("GPU worker operation %s failed", request.op)
        writer.send(WorkerResponse(request.request_id, ok=False, error=str(exc), error_type=type(exc).__name__))
        return
    writer.send(WorkerResponse(request.request_id, ok=True, result=result))


def serve(operations_module: ModuleType, protocol_in: BinaryIO, writer: _ResponseWriter) -> None:
    context = WorkerContext(gpu_allowed=os.environ.get(GPU_ALLOWED_ENV) == "1")
    operations: dict[str, Operation] = operations_module.OPERATIONS
    device = str(operations_module.primary_device(context))
    writer.send(WorkerReady(pid=os.getpid(), device=device))
    logger.info("GPU worker pid=%s ready (device=%s, gpu_allowed=%s)", os.getpid(), device, context.gpu_allowed)
    executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_OPERATIONS, thread_name_prefix="gpu-worker-op")
    while True:
        message = read_frame(protocol_in)
        if message is None:
            logger.info("GPU worker pipe closed; exiting")
            return
        if not isinstance(message, WorkerRequest):
            continue
        if message.op == SHUTDOWN_OP:
            logger.info("GPU worker asked to shut down")
            return
        executor.submit(_execute, operations, context, message, writer)


def main(argv: list[str]) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    protocol_in, protocol_out = _claim_protocol_streams()
    if not _guard_parent():
        os._exit(0)
    writer = _ResponseWriter(protocol_out)
    try:
        serve(importlib.import_module(argv[1]), protocol_in, writer)
    except Exception:
        logger.exception("GPU worker crashed")
        sys.stderr.flush()
        os._exit(1)
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv)
