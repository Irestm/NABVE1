from __future__ import annotations

from typing import Callable

from core.gpu_worker.client import GpuWorkerClient
from core.gpu_worker.policy import WorkerPolicy
from modules.power_management.domain import PowerPolicy
from modules.power_management.service import PowerService, WorkerStatus


def worker_policy(policy: PowerPolicy) -> WorkerPolicy:
    return WorkerPolicy(gpu_allowed=policy.gpu_allowed, idle_timeout_s=float(policy.idle_timeout_s))


def link_gpu_worker(service: PowerService, client: GpuWorkerClient) -> Callable[[], None]:
    def apply(policy: PowerPolicy) -> None:
        client.apply_policy(worker_policy(policy))

    def status() -> WorkerStatus:
        state = client.status()
        return WorkerStatus(running=state.running, device=state.device)

    service.bind_worker_status(status)
    unsubscribe = service.subscribe(apply)
    apply(service.policy())
    return unsubscribe
