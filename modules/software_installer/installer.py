from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass

from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.software_installer import package_map
from modules.software_installer.events import SoftwareInstallFinished

logger = get_logger(__name__)

_INSTALL_TIMEOUT_SECONDS = 900

# Native package managers are tried in this order (whichever is on PATH),
# then the two universal fallbacks. A native package is preferred when the
# map has an id for it — faster, and no extra runtime like Flatpak's.
_LINUX_NATIVE_BACKENDS = ("apt", "dnf", "pacman")
_LINUX_UNIVERSAL_BACKENDS = ("flatpak", "snap")


@dataclass(frozen=True)
class InstallPlan:
    app: str
    backend: str
    package_id: str
    argv: list[str]
    needs_elevation: bool


def _install_argv(backend: str, package_id: str) -> tuple[list[str], bool]:
    if backend == "apt":
        return ["apt-get", "install", "-y", package_id], True
    if backend == "dnf":
        return ["dnf", "install", "-y", package_id], True
    if backend == "pacman":
        return ["pacman", "-S", "--noconfirm", package_id], True
    if backend == "flatpak":
        return ["flatpak", "install", "-y", "flathub", package_id], False
    if backend == "snap":
        return ["snap", "install", package_id], True
    if backend == "winget":
        # winget raises its own UAC prompt when a package needs it.
        return [
            "winget", "install", "--exact", "--id", package_id,
            "--accept-package-agreements", "--accept-source-agreements",
        ], False
    raise ValueError(f"Unknown install backend '{backend}'")


def _elevate(argv: list[str]) -> list[str]:
    if shutil.which("pkexec"):
        return ["pkexec", *argv]
    if shutil.which("sudo"):
        return ["sudo", "-n", *argv]
    return argv


def plan_install(app_name: str, *, system: str | None = None) -> InstallPlan | None:
    """Picks a concrete install command for `app_name`, or None when it
    isn't in package_map or no usable backend is present on this machine."""
    key = package_map.resolve(app_name)
    if key is None:
        return None
    ids = package_map.package_ids(key)
    system = system or platform.system()

    if system == "Windows":
        candidates = [("winget", ids.get("winget"))] if shutil.which("winget") else []
    else:
        native = [
            (backend, ids.get(backend))
            for backend in _LINUX_NATIVE_BACKENDS
            if shutil.which(backend)
        ]
        universal = [
            (backend, ids.get(backend))
            for backend in _LINUX_UNIVERSAL_BACKENDS
            if shutil.which(backend)
        ]
        candidates = native + universal

    for backend, package_id in candidates:
        if not package_id:
            continue
        argv, needs_elevation = _install_argv(backend, package_id)
        return InstallPlan(
            app=key,
            backend=backend,
            package_id=package_id,
            argv=_elevate(argv) if needs_elevation else argv,
            needs_elevation=needs_elevation,
        )
    return None


def run_install_sync(plan: InstallPlan) -> tuple[bool, str]:
    """Blocking install. Returns (success, human-readable Russian message)."""
    logger.info("Installing %s via %s: %s", plan.app, plan.backend, " ".join(plan.argv))
    try:
        result = subprocess.run(
            plan.argv, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return False, f"Установка «{plan.app}» не завершилась за отведённое время."
    except OSError as exc:
        logger.exception("Install of %s failed to start", plan.app)
        return False, f"Не удалось запустить установку «{plan.app}»: {exc}."

    if result.returncode == 0:
        return True, f"«{plan.app}» установлен ({plan.backend})."
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else "неизвестная ошибка"
    logger.error("Install of %s exited %s: %s", plan.app, result.returncode, tail)
    return False, f"Не удалось установить «{plan.app}»: {tail}"


def start_background_install(plan: InstallPlan, bus: MessageBus = message_bus) -> None:
    """Runs run_install_sync on a daemon thread and publishes
    SoftwareInstallFinished when it's done — ProactiveAnnouncer speaks it."""

    def _worker() -> None:
        success, message = run_install_sync(plan)
        try:
            asyncio.run(bus.publish(SoftwareInstallFinished(app=plan.app, success=success, message=message)))
        except Exception:
            logger.exception("Failed to publish SoftwareInstallFinished for %s", plan.app)

    threading.Thread(target=_worker, daemon=True, name=f"install-{plan.app}").start()
