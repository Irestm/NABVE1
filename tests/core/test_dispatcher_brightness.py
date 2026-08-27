from __future__ import annotations

import asyncio

import pytest

import core.dispatcher as dispatcher_module


# Screen brightness voice control (core/dispatcher.py's set_brightness/
# change_brightness/get_brightness) — added alongside the intent.py regex
# patterns and the OS-adapter methods, mirroring the system-volume commands.


class _FakeAdapter:
    def __init__(self, start: int = 60) -> None:
        self.percent = start

    def set_brightness(self, percent: int) -> None:
        self.percent = max(5, min(100, percent))

    def change_brightness(self, delta_percent: int) -> None:
        self.set_brightness(self.percent + delta_percent)

    def get_brightness(self) -> int:
        return self.percent


def _install(monkeypatch: pytest.MonkeyPatch, start: int = 60) -> _FakeAdapter:
    adapter = _FakeAdapter(start)
    monkeypatch.setattr(dispatcher_module, "get_os_adapter", lambda: adapter)
    return adapter


def test_set_brightness_sets_exact_level(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)

    result = asyncio.run(dispatcher_module._handle_set_brightness({"percent": "35"}))

    assert adapter.percent == 35
    assert result["percent"] == 35


def test_set_brightness_requires_percent() -> None:
    with pytest.raises(ValueError):
        asyncio.run(dispatcher_module._handle_set_brightness({}))


def test_set_brightness_clamps_to_safe_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)

    result = asyncio.run(dispatcher_module._handle_set_brightness({"percent": "0"}))

    assert adapter.percent == 5
    assert result["percent"] == 5


def test_change_brightness_is_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch, start=50)

    result = asyncio.run(dispatcher_module._handle_change_brightness({"delta_percent": "20"}))

    assert adapter.percent == 70
    assert result["percent"] == 70


def test_change_brightness_accepts_negative_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch, start=50)

    result = asyncio.run(dispatcher_module._handle_change_brightness({"delta_percent": "-30"}))

    assert adapter.percent == 20
    assert result["percent"] == 20


def test_change_brightness_requires_delta() -> None:
    with pytest.raises(ValueError):
        asyncio.run(dispatcher_module._handle_change_brightness({}))


def test_get_brightness_reports_current_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, start=42)

    result = asyncio.run(dispatcher_module._handle_get_brightness({}))

    assert result["percent"] == 42


def test_brightness_commands_are_registered_and_distinct_from_volume() -> None:
    dispatcher = dispatcher_module.build_dispatcher()
    commands = {c.name for c in dispatcher.list_commands()}
    assert {"set_brightness", "change_brightness", "get_brightness"} <= commands
    assert {"set_volume", "change_volume", "get_volume"} <= commands
