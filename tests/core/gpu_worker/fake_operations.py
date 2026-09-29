from __future__ import annotations

import os
import time
from typing import Any, Callable

from core.gpu_worker.context import WorkerContext


def primary_device(context: WorkerContext) -> str:
    return "cuda" if context.gpu_allowed else "cpu"


def _echo(context: WorkerContext, args: dict[str, Any]) -> Any:
    return args.get("value")


def _environment(context: WorkerContext, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "gpu_allowed": context.gpu_allowed,
    }


def _sleep(context: WorkerContext, args: dict[str, Any]) -> float:
    time.sleep(float(args["seconds"]))
    return float(args["seconds"])


def _crash(context: WorkerContext, args: dict[str, Any]) -> None:
    os._exit(3)


def _fail(context: WorkerContext, args: dict[str, Any]) -> None:
    raise ValueError("bad input")


def _cached_counter(context: WorkerContext, args: dict[str, Any]) -> int:
    return context.cached("counter", lambda: os.getpid())


OPERATIONS: dict[str, Callable[[WorkerContext, dict[str, Any]], Any]] = {
    "echo": _echo,
    "env": _environment,
    "sleep": _sleep,
    "crash": _crash,
    "fail": _fail,
    "cached": _cached_counter,
}
