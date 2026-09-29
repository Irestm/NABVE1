from __future__ import annotations

import os
import time
from typing import Callable, Iterator

import numpy as np
import pytest

from core.gpu_worker.client import (
    GpuWorkerClient,
    GpuWorkerCrashed,
    GpuWorkerOperationError,
    GpuWorkerTimeout,
    GpuWorkerUnavailable,
)
from core.gpu_worker.policy import WorkerPolicy, build_worker_env
from core.gpu_worker.protocol import DISABLED_ENV

FAKE_OPERATIONS = "tests.core.gpu_worker.fake_operations"
_CALL_TIMEOUT = 30.0


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop(DISABLED_ENV, None)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    return env


@pytest.fixture
def make_client() -> Iterator[Callable[..., GpuWorkerClient]]:
    clients: list[GpuWorkerClient] = []

    def factory(policy: WorkerPolicy | None = None, **kwargs: object) -> GpuWorkerClient:
        client = GpuWorkerClient(
            policy or WorkerPolicy(gpu_allowed=True, idle_timeout_s=60.0),
            operations_module=FAKE_OPERATIONS,
            startup_timeout=30.0,
            stop_timeout=3.0,
            base_env=_base_env(),
            **kwargs,  # type: ignore[arg-type]
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.stop()


def _wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def test_worker_starts_on_first_call_and_reports_its_device(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    assert client.status().running is False

    assert client.call("echo", {"value": [1, 2, 3]}, _CALL_TIMEOUT) == [1, 2, 3]

    state = client.status()
    assert state.running is True
    assert state.device == "cuda"
    assert state.pid is not None and state.pid != os.getpid()


def test_numpy_payloads_round_trip(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    audio = np.linspace(-1.0, 1.0, 16000, dtype=np.float32)

    result = client.call("echo", {"value": audio}, _CALL_TIMEOUT)

    assert np.array_equal(result, audio)


def test_models_stay_cached_while_the_worker_lives(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()

    first = client.call("cached", {}, _CALL_TIMEOUT)
    second = client.call("cached", {}, _CALL_TIMEOUT)

    assert first == second == client.status().pid


def test_worker_exits_after_the_idle_timeout(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client(WorkerPolicy(gpu_allowed=True, idle_timeout_s=0.3))
    pid = client.call("env", {}, _CALL_TIMEOUT)["pid"]

    assert _wait_until(lambda: not client.status().running)
    assert _wait_until(lambda: not os.path.exists(f"/proc/{pid}") or _is_zombie(pid))

    assert client.call("env", {}, _CALL_TIMEOUT)["pid"] != pid


def test_idle_timeout_does_not_kill_a_running_call(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client(WorkerPolicy(gpu_allowed=True, idle_timeout_s=0.2))

    assert client.call("sleep", {"seconds": 1.0}, _CALL_TIMEOUT) == 1.0


def test_idle_timeout_can_change_on_the_fly(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client(WorkerPolicy(gpu_allowed=True, idle_timeout_s=600.0))
    client.call("echo", {"value": 1}, _CALL_TIMEOUT)

    client.apply_policy(WorkerPolicy(gpu_allowed=True, idle_timeout_s=0.2))

    assert _wait_until(lambda: not client.status().running)


def test_gpu_is_hidden_from_the_worker_when_not_allowed(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client(WorkerPolicy(gpu_allowed=False, idle_timeout_s=60.0))

    environment = client.call("env", {}, _CALL_TIMEOUT)

    assert environment["cuda_visible_devices"] == ""
    assert environment["gpu_allowed"] is False
    assert client.status().device == "cpu"


def test_gpu_policy_change_restarts_the_worker_once_idle(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client(WorkerPolicy(gpu_allowed=True, idle_timeout_s=600.0))
    before = client.call("env", {}, _CALL_TIMEOUT)
    assert before["cuda_visible_devices"] is None

    client.apply_policy(WorkerPolicy(gpu_allowed=False, idle_timeout_s=600.0))
    assert _wait_until(lambda: not client.status().running)
    after = client.call("env", {}, _CALL_TIMEOUT)

    assert after["pid"] != before["pid"]
    assert after["cuda_visible_devices"] == ""


def test_crash_is_reported_and_the_next_call_gets_a_fresh_worker(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    first_pid = client.call("env", {}, _CALL_TIMEOUT)["pid"]

    with pytest.raises(GpuWorkerCrashed):
        client.call("crash", {}, _CALL_TIMEOUT)

    assert client.call("env", {}, _CALL_TIMEOUT)["pid"] != first_pid


def test_operation_errors_do_not_kill_the_worker(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    pid = client.call("env", {}, _CALL_TIMEOUT)["pid"]

    with pytest.raises(GpuWorkerOperationError) as raised:
        client.call("fail", {}, _CALL_TIMEOUT)

    assert raised.value.error_type == "ValueError"
    assert client.call("env", {}, _CALL_TIMEOUT)["pid"] == pid


def test_timed_out_call_kills_the_worker(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    pid = client.call("env", {}, _CALL_TIMEOUT)["pid"]

    with pytest.raises(GpuWorkerTimeout):
        client.call("sleep", {"seconds": 30}, 0.3)

    assert client.call("env", {}, _CALL_TIMEOUT)["pid"] != pid


def test_stop_terminates_the_worker_and_refuses_new_calls(make_client: Callable[..., GpuWorkerClient]) -> None:
    client = make_client()
    pid = client.call("env", {}, _CALL_TIMEOUT)["pid"]

    client.stop()

    assert client.status().running is False
    assert _wait_until(lambda: not os.path.exists(f"/proc/{pid}") or _is_zombie(pid))
    with pytest.raises(GpuWorkerUnavailable):
        client.call("echo", {"value": 1}, _CALL_TIMEOUT)


def test_disabled_worker_is_never_spawned() -> None:
    client = GpuWorkerClient(operations_module=FAKE_OPERATIONS, base_env={**_base_env(), DISABLED_ENV: "1"})

    with pytest.raises(GpuWorkerUnavailable):
        client.call("echo", {"value": 1}, _CALL_TIMEOUT)


def test_worker_env_hides_cuda_only_when_gpu_is_forbidden() -> None:
    allowed = build_worker_env({"CUDA_VISIBLE_DEVICES": "0"}, gpu_allowed=True, parent_pid=10)
    forbidden = build_worker_env({"CUDA_VISIBLE_DEVICES": "0"}, gpu_allowed=False, parent_pid=10)

    assert allowed["CUDA_VISIBLE_DEVICES"] == "0"
    assert forbidden["CUDA_VISIBLE_DEVICES"] == ""
    assert forbidden["ASSISTANT_GPU_WORKER_PARENT_PID"] == "10"


def _is_zombie(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stat:
            return stat.read().split(")")[-1].split()[0] == "Z"
    except OSError:
        return True
