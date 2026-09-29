from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.gpu_worker.protocol import CUDA_VISIBLE_DEVICES_ENV, GPU_ALLOWED_ENV, PARENT_PID_ENV

DEFAULT_IDLE_TIMEOUT_SECONDS = 900.0


@dataclass(frozen=True)
class WorkerPolicy:
    gpu_allowed: bool = True
    idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_SECONDS


def build_worker_env(base: Mapping[str, str], gpu_allowed: bool, parent_pid: int) -> dict[str, str]:
    env = dict(base)
    env[GPU_ALLOWED_ENV] = "1" if gpu_allowed else "0"
    env[PARENT_PID_ENV] = str(parent_pid)
    env["PYTHONUNBUFFERED"] = "1"
    if not gpu_allowed:
        env[CUDA_VISIBLE_DEVICES_ENV] = ""
    return env
