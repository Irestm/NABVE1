from __future__ import annotations

import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from core.watchdog.supervisor import Supervisor


def _supervisor(**overrides: object) -> Supervisor:
    defaults: dict[str, object] = dict(
        host="127.0.0.1",
        port=8756,
        bind_host="0.0.0.0",
        check_interval=0.01,
        health_timeout=0.01,
        max_consecutive_failures=3,
        initial_backoff=0.01,
        max_backoff=0.03,
        healthy_reset_seconds=60.0,
    )
    defaults.update(overrides)
    return Supervisor(**defaults)


def test_check_health_true_on_2xx_response() -> None:
    supervisor = _supervisor()
    fake_response = MagicMock(status=200)
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("core.watchdog.supervisor.urllib.request.urlopen", return_value=fake_response):
        assert supervisor._check_health() is True


def test_check_health_false_on_non_2xx_response() -> None:
    supervisor = _supervisor()
    fake_response = MagicMock(status=500)
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("core.watchdog.supervisor.urllib.request.urlopen", return_value=fake_response):
        assert supervisor._check_health() is False


def test_check_health_false_and_does_not_raise_on_connection_error() -> None:
    supervisor = _supervisor()

    with patch(
        "core.watchdog.supervisor.urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")
    ):
        assert supervisor._check_health() is False


def test_spawn_starts_a_process_and_resets_failure_count() -> None:
    supervisor = _supervisor()
    supervisor._consecutive_failures = 2
    fake_process = MagicMock(pid=1234)

    with patch("core.watchdog.supervisor.subprocess.Popen", return_value=fake_process) as popen:
        supervisor._spawn()

    popen.assert_called_once()
    assert supervisor._process is fake_process
    assert supervisor._consecutive_failures == 0


def test_terminate_is_a_no_op_when_process_already_exited() -> None:
    supervisor = _supervisor()
    fake_process = MagicMock()
    fake_process.poll.return_value = 0
    supervisor._process = fake_process

    supervisor._terminate("test")

    fake_process.terminate.assert_not_called()
    assert supervisor._process is None


def test_terminate_sends_sigterm_then_waits() -> None:
    supervisor = _supervisor()
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    fake_process.wait.return_value = 0
    supervisor._process = fake_process

    supervisor._terminate("test")

    fake_process.terminate.assert_called_once()
    fake_process.wait.assert_called_once()
    assert supervisor._process is None


def test_terminate_kills_if_sigterm_times_out() -> None:
    supervisor = _supervisor()
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    fake_process.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=1), 0]
    supervisor._process = fake_process

    supervisor._terminate("test")

    fake_process.kill.assert_called_once()
    assert supervisor._process is None


def test_wait_backoff_doubles_up_to_the_max() -> None:
    supervisor = _supervisor(initial_backoff=0.01, max_backoff=0.03)

    supervisor._wait_backoff()
    assert supervisor._backoff == pytest.approx(0.02)

    supervisor._wait_backoff()
    assert supervisor._backoff == pytest.approx(0.03)

    supervisor._wait_backoff()
    assert supervisor._backoff == pytest.approx(0.03)


def test_restart_terminates_waits_and_respawns() -> None:
    supervisor = _supervisor()
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    fake_process.wait.return_value = 0
    supervisor._process = fake_process

    with patch("core.watchdog.supervisor.subprocess.Popen", return_value=MagicMock(pid=999)) as popen:
        supervisor._restart("test reason")

    popen.assert_called_once()
    assert supervisor._process is not None


def test_restart_does_not_respawn_if_stop_requested_during_backoff() -> None:
    supervisor = _supervisor()
    supervisor._process = None

    def _set_stop_during_wait() -> None:
        supervisor._stop_event.set()

    with patch.object(supervisor, "_wait_backoff", side_effect=_set_stop_during_wait), patch(
        "core.watchdog.supervisor.subprocess.Popen"
    ) as popen:
        supervisor._restart("test reason")

    popen.assert_not_called()
