from __future__ import annotations

import asyncio

import pytest

from core.dispatcher import CommandDispatcher
from modules.software_installer import handlers, installer
from modules.software_installer.installer import InstallPlan


def test_install_known_app_kicks_off_background_and_answers_immediately(monkeypatch) -> None:
    started: list[InstallPlan] = []
    plan = InstallPlan("vlc", "apt", "vlc", ["apt-get", "install", "-y", "vlc"], True)
    monkeypatch.setattr(handlers.installer, "plan_install", lambda app: plan)
    monkeypatch.setattr(handlers.installer, "start_background_install", lambda p: started.append(p))

    result = asyncio.run(handlers._handle_software_install({"app": "vlc"}))

    assert started == [plan]
    assert result["known"] is True
    assert "фоне" in result["message"]


def test_install_unknown_app_gives_manual_hint() -> None:
    result = asyncio.run(handlers._handle_software_install({"app": "какая-то программа"}))

    assert result["known"] is False
    assert "вручную" in result["message"]


def test_install_known_but_no_backend_gives_hint(monkeypatch) -> None:
    monkeypatch.setattr(handlers.installer, "plan_install", lambda app: None)

    result = asyncio.run(handlers._handle_software_install({"app": "vlc"}))

    assert result["known"] is True
    assert "пакетн" in result["message"]


def test_install_requires_an_app() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_software_install({}))


def test_installer_click_button_delegates(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "click_installer_button", lambda kind: f"clicked {kind}")

    result = asyncio.run(handlers._handle_installer_click_button({"button": "install"}))

    assert result == {"button": "install", "message": "clicked install"}


def test_installer_click_button_turns_failures_into_runtime_error(monkeypatch) -> None:
    def _boom(kind):
        raise handlers.InstallerButtonNotFoundError("no button")

    monkeypatch.setattr(handlers, "click_installer_button", _boom)

    with pytest.raises(RuntimeError, match="no button"):
        asyncio.run(handlers._handle_installer_click_button({"button": "next"}))


def test_commands_register() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)
    names = {c.name for c in dispatcher.list_commands()}
    assert {"software_install", "installer_click_button"} <= names
