from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.ai_bridge import virtual_display

# Captured before the autouse fixture below rebinds virtual_display's own
# module attribute to a deterministic stub — the three _find_live_xvfb_pid
# tests want the real implementation, not that stub.
_real_find_live_xvfb_pid = virtual_display._find_live_xvfb_pid


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    virtual_display._process = None
    virtual_display._ready = None
    virtual_display._unavailable = False
    # Deterministic by default, regardless of what's actually running on the
    # machine these tests happen to execute on — this dev box, for one,
    # routinely has its own real backend's Xvfb alive at the real lock path
    # (and, live-testing turned up, sometimes a genuinely orphaned one with
    # no lock file at all — exactly what _find_live_xvfb_pid's real /proc
    # scan would find) these tests would otherwise read for real. Tests
    # that specifically exercise the lock-reuse/proc-scan-reuse behavior
    # override these themselves.
    monkeypatch.setattr(virtual_display, "_lock_owner_pid", lambda: None)
    monkeypatch.setattr(virtual_display, "_find_live_xvfb_pid", lambda: None)
    yield
    if virtual_display._process is not None:
        virtual_display._process.terminate()
    virtual_display._process = None
    virtual_display._ready = None
    virtual_display._unavailable = False


@pytest.mark.asyncio
async def test_get_display_returns_none_when_xvfb_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: None)

    result = await virtual_display.get_display()

    assert result is None
    assert virtual_display._unavailable is True


@pytest.mark.asyncio
async def test_get_display_starts_xvfb_and_returns_display_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    monkeypatch.setattr(virtual_display.subprocess, "Popen", lambda *a, **k: fake_process)

    result = await virtual_display.get_display()

    assert result == virtual_display._DISPLAY


@pytest.mark.asyncio
async def test_get_display_is_cached_after_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    popen_calls: list[object] = []

    def fake_popen(*args: object, **kwargs: object) -> MagicMock:
        popen_calls.append(args)
        return fake_process

    monkeypatch.setattr(virtual_display.subprocess, "Popen", fake_popen)

    first = await virtual_display.get_display()
    second = await virtual_display.get_display()

    assert first == second
    assert len(popen_calls) == 1


@pytest.mark.asyncio
async def test_get_display_reuses_a_live_xvfb_left_by_an_earlier_process(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: an earlier backend process's Xvfb, still running because it
    # never got to call stop() on shutdown, used to be treated as a stale
    # lock - deleted, then a second Xvfb was started on the same display
    # number, which fails to bind (the display is genuinely still in use)
    # and silently falls back to a REAL, visible browser window instead of
    # the hidden one this module exists to guarantee.
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    monkeypatch.setattr(virtual_display, "_lock_owner_pid", lambda: 12345)
    monkeypatch.setattr(virtual_display, "_process_is_alive", lambda pid: True)
    popen_calls: list[object] = []
    monkeypatch.setattr(
        virtual_display.subprocess, "Popen", lambda *a, **k: popen_calls.append(1) or MagicMock()
    )

    result = await virtual_display.get_display()

    assert result == virtual_display._DISPLAY
    assert popen_calls == []  # never tried to start a second, competing Xvfb
    assert virtual_display._process is None  # not ours to stop() later


@pytest.mark.asyncio
async def test_get_display_starts_fresh_when_lock_owner_is_actually_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    monkeypatch.setattr(virtual_display, "_lock_owner_pid", lambda: 12345)
    monkeypatch.setattr(virtual_display, "_process_is_alive", lambda pid: False)
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    monkeypatch.setattr(virtual_display.subprocess, "Popen", lambda *a, **k: fake_process)

    result = await virtual_display.get_display()

    assert result == virtual_display._DISPLAY
    assert virtual_display._process is fake_process


@pytest.mark.asyncio
async def test_get_display_returns_none_when_xvfb_exits_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    fake_process = MagicMock()
    fake_process.poll.return_value = 1
    fake_process.returncode = 1
    monkeypatch.setattr(virtual_display.subprocess, "Popen", lambda *a, **k: fake_process)

    result = await virtual_display.get_display()

    assert result is None
    assert virtual_display._unavailable is True


def test_find_live_xvfb_pid_returns_pid_of_matching_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.os, "listdir", lambda path: ["1", "42", "not-a-pid"])

    def fake_read_bytes(self: Path) -> bytes:
        if self == Path("/proc", "42", "cmdline"):
            return b"Xvfb\x00:97\x00-screen\x000\x001280x1024x24\x00-nolisten\x00tcp\x00"
        if self == Path("/proc", "1", "cmdline"):
            return b"/sbin/init\x00"
        raise OSError

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    assert _real_find_live_xvfb_pid() == 42


def test_find_live_xvfb_pid_returns_none_when_no_process_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.os, "listdir", lambda path: ["1"])
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"/sbin/init\x00")

    assert _real_find_live_xvfb_pid() is None


def test_find_live_xvfb_pid_ignores_xvfb_on_a_different_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.os, "listdir", lambda path: ["7"])
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"Xvfb\x00:5\x00-screen\x000\x00")

    assert _real_find_live_xvfb_pid() is None


def test_find_live_xvfb_pid_returns_none_when_proc_itself_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_listdir(path: str) -> list[str]:
        raise OSError("simulated: /proc not readable")

    monkeypatch.setattr(virtual_display.os, "listdir", fake_listdir)

    assert _real_find_live_xvfb_pid() is None


def test_find_live_xvfb_pid_skips_a_pid_whose_cmdline_disappeared_mid_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A process can exit between os.listdir("/proc") listing its directory
    # and this reading its cmdline (classic /proc race) - that one pid's
    # OSError must not abort the whole scan, just skip it and keep looking.
    monkeypatch.setattr(virtual_display.os, "listdir", lambda path: ["1", "42"])

    def fake_read_bytes(self: Path) -> bytes:
        if self == Path("/proc", "1", "cmdline"):
            raise OSError("simulated: process exited")
        return b"Xvfb\x00:97\x00-screen\x000\x00"

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    assert _real_find_live_xvfb_pid() == 42


@pytest.mark.asyncio
async def test_get_display_reuses_a_live_xvfb_found_via_proc_scan_when_lock_file_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression, found live: this environment's Xvfb binds an abstract-
    # namespace socket, so a genuinely running server leaves no
    # /tmp/.X11-unix/X97 file to fall back on either — and a hard-killed
    # process can leave no /tmp/.X97-lock file at all. The lock-file-only
    # check used to treat a real, still-running orphaned Xvfb as dead and
    # try (and fail) to bind a second, competing one on the same display.
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    monkeypatch.setattr(virtual_display, "_lock_owner_pid", lambda: None)
    monkeypatch.setattr(virtual_display, "_find_live_xvfb_pid", lambda: 999)
    monkeypatch.setattr(virtual_display, "_process_is_alive", lambda pid: pid == 999)
    popen_calls: list[object] = []
    monkeypatch.setattr(
        virtual_display.subprocess, "Popen", lambda *a, **k: popen_calls.append(1) or MagicMock()
    )

    result = await virtual_display.get_display()

    assert result == virtual_display._DISPLAY
    assert popen_calls == []  # never tried to start a second, competing Xvfb
    assert virtual_display._process is None  # not ours to stop() later


@pytest.mark.asyncio
async def test_get_display_retries_once_after_clearing_stale_files_when_first_bind_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression, found live: an immediate exit here (code 1) despite the
    # lock-owner check above already confirming no live Xvfb to reuse means
    # something else is blocking the bind — most often a stale
    # /tmp/.X11-unix/X97 socket left by a process that died hard enough to
    # skip its own cleanup. The old code gave up on the very first failure,
    # which routinely meant a REAL, visible browser window for the rest of
    # that process's lifetime instead of just this one request.
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    failed_process = MagicMock()
    failed_process.poll.return_value = 1
    failed_process.returncode = 1
    succeeded_process = MagicMock()
    succeeded_process.poll.return_value = None
    processes = iter([failed_process, succeeded_process])
    popen_calls: list[object] = []
    monkeypatch.setattr(
        virtual_display.subprocess, "Popen", lambda *a, **k: popen_calls.append(1) or next(processes)
    )
    cleared: list[bool] = []
    monkeypatch.setattr(virtual_display, "_clear_stale_display_files", lambda: cleared.append(True))

    result = await virtual_display.get_display()

    assert result == virtual_display._DISPLAY
    assert len(popen_calls) == 2  # first attempt failed, retried once after cleanup
    assert cleared == [True]
    assert virtual_display._process is succeeded_process


@pytest.mark.asyncio
async def test_get_display_gives_up_after_retry_also_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    fake_process = MagicMock()
    fake_process.poll.return_value = 1
    fake_process.returncode = 1
    popen_calls: list[object] = []
    monkeypatch.setattr(
        virtual_display.subprocess, "Popen", lambda *a, **k: popen_calls.append(1) or fake_process
    )
    monkeypatch.setattr(virtual_display, "_clear_stale_display_files", lambda: None)

    result = await virtual_display.get_display()

    assert result is None
    assert virtual_display._unavailable is True
    assert len(popen_calls) == 2  # tried once, retried once, then actually gave up


def test_stop_terminates_process_and_clears_state() -> None:
    fake_process = MagicMock()
    virtual_display._process = fake_process
    virtual_display._ready = virtual_display._DISPLAY

    virtual_display.stop()

    fake_process.terminate.assert_called_once()
    fake_process.wait.assert_called_once()
    assert virtual_display._process is None
    assert virtual_display._ready is None


def test_stop_kills_the_process_if_it_does_not_exit_after_terminate() -> None:
    # Regression: stop() used to return right after terminate() without
    # waiting at all — since this process itself usually exits right after
    # stop() returns (see core/main.py's shutdown lifespan), that raced
    # Xvfb's own cleanup and could leave a stale /tmp/.X11-unix/X97 socket
    # for the next process's get_display() to trip over.
    fake_process = MagicMock()
    fake_process.wait.side_effect = [subprocess.TimeoutExpired(cmd="Xvfb", timeout=3), None]
    virtual_display._process = fake_process
    virtual_display._ready = virtual_display._DISPLAY

    virtual_display.stop()

    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_called_once()
    assert fake_process.wait.call_count == 2
    assert virtual_display._process is None


def test_stop_is_a_noop_when_nothing_was_started() -> None:
    virtual_display.stop()  # should not raise
