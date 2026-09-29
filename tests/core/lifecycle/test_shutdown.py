from __future__ import annotations

import signal
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.lifecycle import http_api, parent_death, shutdown


def test_request_shutdown_signals_the_watchdog_when_supervised(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setenv(shutdown.SUPERVISED_ENV, "1")
    monkeypatch.setenv(shutdown.SUPERVISOR_PID_ENV, "4321")
    monkeypatch.setattr(shutdown.os, "getppid", lambda: 4321)
    monkeypatch.setattr(shutdown.os, "name", "posix")
    monkeypatch.setattr(shutdown.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(shutdown, "terminate_self", lambda: killed.append((-1, -1)))

    shutdown.request_process_shutdown()

    assert killed == [(4321, signal.SIGTERM)]


def test_request_shutdown_stops_itself_when_the_watchdog_is_already_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setenv(shutdown.SUPERVISED_ENV, "1")
    monkeypatch.setenv(shutdown.SUPERVISOR_PID_ENV, "4321")
    monkeypatch.setattr(shutdown.os, "getppid", lambda: 1)
    monkeypatch.setattr(shutdown.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(shutdown, "terminate_self", lambda: killed.append((-1, -1)))

    shutdown.request_process_shutdown()

    assert killed == [(-1, -1)]


def test_request_shutdown_stops_itself_when_not_supervised(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.delenv(shutdown.SUPERVISED_ENV, raising=False)
    monkeypatch.setattr(shutdown.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(shutdown, "terminate_self", lambda: killed.append((-1, -1)))

    shutdown.request_process_shutdown()

    assert killed == [(-1, -1)]


def test_guard_is_not_installed_outside_the_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(shutdown.SUPERVISED_ENV, raising=False)

    assert shutdown.install_supervised_child_guard() is None


def test_guard_stops_the_process_if_the_watchdog_died_during_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    terminated: list[bool] = []
    monkeypatch.setenv(shutdown.SUPERVISED_ENV, "1")
    monkeypatch.setenv(shutdown.SUPERVISOR_PID_ENV, "4321")
    monkeypatch.setattr(shutdown, "set_parent_death_signal", lambda signum: True)
    monkeypatch.setattr(parent_death.os, "getppid", lambda: 1)
    monkeypatch.setattr(shutdown, "terminate_self", lambda: terminated.append(True))

    assert shutdown.install_supervised_child_guard() is None
    assert terminated == [True]


def test_parent_watcher_fires_once_the_parent_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    fired = threading.Event()
    parents = iter([100, 100, 1])
    monkeypatch.setattr(parent_death.os, "getppid", lambda: next(parents, 1))
    watcher = parent_death.ParentWatcher(100, fired.set, interval_seconds=0.01)

    watcher.start()

    assert fired.wait(2.0)
    watcher.stop()


def test_run_bounded_returns_unfinished_steps_without_waiting_for_them() -> None:
    release = threading.Event()
    finished: list[str] = []

    def _fast() -> None:
        finished.append("fast")

    def _failing() -> None:
        raise RuntimeError("boom")

    started = time.monotonic()
    unfinished = shutdown.run_bounded(
        [("fast", _fast), ("failing", _failing), ("hanging", lambda: release.wait(5.0))],
        0.2,
    )
    elapsed = time.monotonic() - started
    release.set()

    assert unfinished == ["hanging"]
    assert finished == ["fast"]
    assert elapsed < 1.0


def test_set_parent_death_signal_is_a_no_op_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_death.sys, "platform", "win32")

    assert parent_death.set_parent_death_signal() is False


def test_shutdown_endpoint_answers_202_before_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduled: list[bool] = []
    monkeypatch.setattr(http_api, "schedule_shutdown", lambda: scheduled.append(True))
    app = FastAPI()
    app.include_router(http_api.router)

    response = TestClient(app).post("/api/system/shutdown")

    assert response.status_code == 202
    assert response.json() == {"ok": True}
    assert scheduled == [True]
