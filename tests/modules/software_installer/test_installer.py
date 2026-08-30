from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock

from core.message_bus import MessageBus
from modules.software_installer import installer
from modules.software_installer.events import SoftwareInstallFinished


def _only(names: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_plan_install_prefers_native_apt_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(installer.shutil, "which", _only({"apt", "flatpak", "pkexec"}))

    plan = installer.plan_install("vlc", system="Linux")

    assert plan is not None
    assert plan.backend == "apt"
    assert plan.package_id == "vlc"
    assert plan.argv[:2] == ["pkexec", "apt-get"]
    assert plan.needs_elevation is True


def test_plan_install_falls_back_to_flatpak_when_no_native_id(monkeypatch) -> None:
    # chrome has no apt/dnf/pacman id in the map.
    monkeypatch.setattr(installer.shutil, "which", _only({"apt", "flatpak"}))

    plan = installer.plan_install("chrome", system="Linux")

    assert plan is not None
    assert plan.backend == "flatpak"
    assert plan.package_id == "com.google.Chrome"
    assert plan.argv[0] == "flatpak"
    assert plan.needs_elevation is False


def test_plan_install_uses_winget_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(installer.shutil, "which", _only({"winget"}))

    plan = installer.plan_install("obs", system="Windows")

    assert plan is not None
    assert plan.backend == "winget"
    assert plan.package_id == "OBSProject.OBSStudio"
    assert "--id" in plan.argv


def test_plan_install_returns_none_for_unknown_app(monkeypatch) -> None:
    monkeypatch.setattr(installer.shutil, "which", _only({"apt"}))
    assert installer.plan_install("будильник", system="Linux") is None


def test_plan_install_returns_none_when_no_backend_present(monkeypatch) -> None:
    monkeypatch.setattr(installer.shutil, "which", _only(set()))
    assert installer.plan_install("vlc", system="Linux") is None


def test_run_install_sync_reports_success(monkeypatch) -> None:
    monkeypatch.setattr(
        installer.subprocess, "run", lambda *a, **k: MagicMock(returncode=0, stdout="done", stderr="")
    )
    plan = installer.InstallPlan("vlc", "apt", "vlc", ["apt-get", "install", "-y", "vlc"], True)

    ok, message = installer.run_install_sync(plan)

    assert ok is True
    assert "установлен" in message


def test_run_install_sync_reports_failure_tail(monkeypatch) -> None:
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=100, stdout="", stderr="E: Unable to locate package vlc"),
    )
    plan = installer.InstallPlan("vlc", "apt", "vlc", ["apt-get", "install", "-y", "vlc"], True)

    ok, message = installer.run_install_sync(plan)

    assert ok is False
    assert "Unable to locate package" in message


def test_run_install_sync_handles_timeout(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="apt-get", timeout=1)

    monkeypatch.setattr(installer.subprocess, "run", _boom)
    plan = installer.InstallPlan("vlc", "apt", "vlc", ["apt-get"], True)

    ok, message = installer.run_install_sync(plan)
    assert ok is False and "время" in message


def test_start_background_install_publishes_finished_event(monkeypatch) -> None:
    monkeypatch.setattr(installer, "run_install_sync", lambda plan: (True, "«vlc» установлен (apt)."))
    bus = MessageBus()
    received: list[SoftwareInstallFinished] = []

    async def handler(event: SoftwareInstallFinished) -> None:
        received.append(event)

    bus.subscribe(SoftwareInstallFinished, handler)
    plan = installer.InstallPlan("vlc", "apt", "vlc", ["apt-get"], True)

    installer.start_background_install(plan, bus=bus)

    for _ in range(200):
        if received:
            break
        import time

        time.sleep(0.01)

    assert len(received) == 1
    assert received[0].app == "vlc" and received[0].success is True
