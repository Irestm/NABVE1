from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from modules.ai_bridge import virtual_display


@pytest.fixture(autouse=True)
def _reset_state():
    virtual_display._process = None
    virtual_display._ready = None
    virtual_display._unavailable = False
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
async def test_get_display_returns_none_when_xvfb_exits_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_display.shutil, "which", lambda name: "/usr/bin/Xvfb")
    fake_process = MagicMock()
    fake_process.poll.return_value = 1
    fake_process.returncode = 1
    monkeypatch.setattr(virtual_display.subprocess, "Popen", lambda *a, **k: fake_process)

    result = await virtual_display.get_display()

    assert result is None
    assert virtual_display._unavailable is True


def test_stop_terminates_process_and_clears_state() -> None:
    fake_process = MagicMock()
    virtual_display._process = fake_process
    virtual_display._ready = virtual_display._DISPLAY

    virtual_display.stop()

    fake_process.terminate.assert_called_once()
    assert virtual_display._process is None
    assert virtual_display._ready is None


def test_stop_is_a_noop_when_nothing_was_started() -> None:
    virtual_display.stop()  # should not raise
