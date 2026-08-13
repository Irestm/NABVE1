from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from core.logger import get_logger
from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.steam import list_steam_games

logger = get_logger(__name__)


def _start_menu_dirs() -> tuple[Path, ...]:
    dirs = []
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        dirs.append(Path(program_data) / "Microsoft/Windows/Start Menu/Programs")
    app_data = os.environ.get("APPDATA")
    if app_data:
        dirs.append(Path(app_data) / "Microsoft/Windows/Start Menu/Programs")
    return tuple(dirs)


_START_MENU_DIRS: tuple[Path, ...] = _start_menu_dirs()


def list_shortcut_apps(start_menu_dirs: Sequence[Path] = _START_MENU_DIRS) -> list[InstalledApp]:
    """Every Start Menu shortcut (common + current user), keyed by its
    display name. Deliberately doesn't resolve the shortcut's real target
    path — `start` (see core/os_adapter/windows.py's open_application)
    already follows a .lnk shortcut natively, so the shortcut file itself
    is a perfectly good launch target and no shortcut-parsing dependency
    (pywin32's WScript.Shell) is needed."""
    seen_names: set[str] = set()
    apps: list[InstalledApp] = []
    for directory in start_menu_dirs:
        if not directory.is_dir():
            continue
        for shortcut_path in sorted(directory.rglob("*.lnk")):
            name = shortcut_path.stem
            if name in seen_names:
                continue
            seen_names.add(name)
            apps.append(InstalledApp(display_name=name, launch_target=str(shortcut_path), source="shortcut"))
    return apps


def _steam_root_from_registry() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None

    for hive, subkey in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
                return Path(value)
        except OSError:
            continue
    return None


def list_installed_apps(
    start_menu_dirs: Sequence[Path] = _START_MENU_DIRS, steam_root: Path | None = None
) -> list[InstalledApp]:
    apps = list_shortcut_apps(start_menu_dirs)

    resolved_steam_root = steam_root if steam_root is not None else _steam_root_from_registry()
    if resolved_steam_root is not None and resolved_steam_root.is_dir():
        apps.extend(list_steam_games(resolved_steam_root))
    else:
        logger.debug("Steam install not found via registry; skipping Steam games")
    return apps
