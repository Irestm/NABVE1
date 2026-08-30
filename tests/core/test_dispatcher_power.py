from __future__ import annotations

import asyncio

import pytest

import core.dispatcher as dispatcher_module
from core.models import CommandStatus


class _FakeAdapter:
    def __init__(self, profile: str = "balanced") -> None:
        self.suspended = False
        self.profile = profile

    def suspend(self) -> None:
        self.suspended = True

    def get_power_profile(self) -> str:
        return self.profile

    def set_power_profile(self, profile: str) -> None:
        self.profile = profile


def _install(monkeypatch: pytest.MonkeyPatch, **kwargs) -> _FakeAdapter:
    adapter = _FakeAdapter(**kwargs)
    monkeypatch.setattr(dispatcher_module, "get_os_adapter", lambda: adapter)
    return adapter


def test_suspend_handler_calls_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)
    result = asyncio.run(dispatcher_module._handle_suspend({}))
    assert adapter.suspended is True
    assert "спящий" in result["message"]


def test_suspend_is_registered_without_confirmation() -> None:
    dispatcher = dispatcher_module.build_dispatcher()
    commands = {c.name: c for c in dispatcher.list_commands()}
    assert "suspend" in commands
    assert commands["suspend"].dangerous is False


def test_suspend_dispatch_executes_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install(monkeypatch)
    dispatcher = dispatcher_module.build_dispatcher()

    response = asyncio.run(dispatcher.dispatch("suspend", {}))

    assert response.status == CommandStatus.EXECUTED
    assert adapter.suspended is True


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("power-saver", "power-saver"),
        ("Экономия энергии", "power-saver"),
        ("энергосбережение", "power-saver"),
        ("Сбалансированный", "balanced"),
        ("производительность", "performance"),
        ("performance", "performance"),
    ],
)
def test_set_power_profile_normalizes_synonyms(monkeypatch, spoken, expected) -> None:
    adapter = _install(monkeypatch)
    result = asyncio.run(dispatcher_module._handle_set_power_profile({"mode": spoken}))
    assert adapter.profile == expected
    assert result["profile"] == expected


def test_set_power_profile_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        asyncio.run(dispatcher_module._handle_set_power_profile({"mode": "турбо"}))


def test_get_power_profile_reports_current(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, profile="performance")
    result = asyncio.run(dispatcher_module._handle_get_power_profile({}))
    assert result["profile"] == "performance"
    assert "производительность" in result["message"]
