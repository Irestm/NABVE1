from __future__ import annotations

import asyncio

import pytest

import core.dispatcher as dispatcher_module
from core.models import CommandStatus


# Screen lock (core/dispatcher.py's lock_screen) — a session action distinct
# from shutdown/restart: nothing is closed, only the desktop is locked. Still
# dangerous=True so it goes through the same spoken-confirmation flow.


class _FakeAdapter:
    def __init__(self) -> None:
        self.locked = False

    def lock_screen(self) -> None:
        self.locked = True


def _install(monkeypatch: pytest.MonkeyPatch) -> _FakeAdapter:
    adapter = _FakeAdapter()
    monkeypatch.setattr(dispatcher_module, "get_os_adapter", lambda: adapter)
    return adapter


def test_handle_lock_screen_calls_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)

    result = asyncio.run(dispatcher_module._handle_lock_screen({}))

    assert adapter.locked is True
    assert result["message"] == "Экран заблокирован."


def test_lock_screen_is_registered_as_dangerous() -> None:
    dispatcher = dispatcher_module.build_dispatcher()
    commands = {c.name: c for c in dispatcher.list_commands()}
    assert "lock_screen" in commands
    assert commands["lock_screen"].dangerous is True


def test_lock_screen_dispatch_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)
    dispatcher = dispatcher_module.build_dispatcher()

    response = asyncio.run(dispatcher.dispatch("lock_screen", {}))

    assert response.status == CommandStatus.CONFIRMATION_REQUIRED
    assert response.token
    assert adapter.locked is False

    approved = asyncio.run(dispatcher.confirm(response.token, approved=True))
    assert approved.status == CommandStatus.EXECUTED
    assert adapter.locked is True
