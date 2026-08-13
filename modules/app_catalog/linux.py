from __future__ import annotations

import os
import shlex
from collections.abc import Sequence
from pathlib import Path

from core.logger import get_logger
from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.steam import list_steam_games

logger = get_logger(__name__)

_DESKTOP_DIRS: tuple[Path, ...] = (
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
    # Flatpak exports each installed app's .desktop file here (a symlink
    # farm, not the app's own install dir) — system-wide and per-user
    # installs land in different trees.
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
    # Snap's equivalent aggregated location.
    Path("/var/lib/snapd/desktop/applications"),
)

_STEAM_ROOTS: tuple[Path, ...] = (
    Path.home() / ".steam/steam",
    Path.home() / ".local/share/Steam",
    # Steam itself installed via Flatpak (com.valvesoftware.Steam) keeps its
    # data under Flatpak's sandboxed per-app home instead of the usual
    # ~/.steam - a different root entirely, not just a different subpath.
    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
)

# AppImages are just standalone executables with no package-manager
# registration at all — there's no system registry to query, so the best
# we can do is look in the handful of places people conventionally keep
# them. An AppImage integrated via AppImageLauncher (which creates a real
# .desktop entry in ~/.local/share/applications) is already covered by the
# desktop-file scan above; this catches the ones that aren't.
_APPIMAGE_DIRS: tuple[Path, ...] = (
    Path.home() / "Applications",
    Path.home() / ".local/share/applications",
    Path.home() / "Downloads",
    Path.home() / ".local/bin",
    Path.home() / "bin",
)


def _resolve_flatpak_launch(tokens: list[str]) -> str | None:
    """Flatpak's exported .desktop Exec lines look like
    "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=... org.telegram.desktop @@u %u @@"
    — naively taking tokens[0] would just run bare `flatpak` with no
    arguments, which does nothing. The actual launch only needs the app id
    (a reverse-DNS-style token with at least two dots) — "flatpak run
    <app-id>" is Flatpak's own default entry point for the app regardless
    of which --command/--branch flags happened to be exported. Returns None
    for a non-Flatpak Exec line."""
    if not tokens or Path(tokens[0]).name != "flatpak":
        return None
    for token in tokens[1:]:
        if token.count(".") >= 2 and not token.startswith(("-", "@", "%")):
            return f"flatpak run {token}"
    return None


def _parse_desktop_entry(path: Path) -> InstalledApp | None:
    """Reads the [Desktop Entry] section of a single .desktop file. Returns
    None for anything not meant to be shown as a launchable app: missing
    Name/Exec, or explicitly NoDisplay/Hidden (helper/background entries
    like "*-print-settings.desktop" or a MIME-handler-only entry) — showing
    those as candidates would just confuse the AI resolver (a later step)
    with things a user would never actually ask to "open"."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    name: str | None = None
    exec_line: str | None = None
    no_display = False
    hidden = False
    in_desktop_entry_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_desktop_entry_section = stripped == "[Desktop Entry]"
            continue
        if not in_desktop_entry_section or "=" not in stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "Name" and name is None:
            name = value
        elif key == "Exec":
            exec_line = value
        elif key == "NoDisplay":
            no_display = value.lower() == "true"
        elif key == "Hidden":
            hidden = value.lower() == "true"

    if not name or not exec_line or no_display or hidden:
        return None

    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        # Unbalanced quotes - a malformed Exec line, not worth guessing at.
        logger.debug("Could not parse Exec line in %s: %r", path, exec_line)
        return None
    if not tokens:
        return None

    # The executable is normally just the first token, with everything
    # after being arguments/field codes (%f, %U, ...) open_application() has
    # no use for. Flatpak is the one common exception: its exported Exec
    # line's first token alone (bare `flatpak`) doesn't launch anything.
    launch_target = _resolve_flatpak_launch(tokens) or tokens[0]
    return InstalledApp(display_name=name, launch_target=launch_target, source="desktop")


def list_desktop_apps(desktop_dirs: Sequence[Path] = _DESKTOP_DIRS) -> list[InstalledApp]:
    seen_names: set[str] = set()
    apps: list[InstalledApp] = []
    for directory in desktop_dirs:
        if not directory.is_dir():
            continue
        for entry_path in sorted(directory.glob("*.desktop")):
            app = _parse_desktop_entry(entry_path)
            if app is None or app.display_name in seen_names:
                continue
            seen_names.add(app.display_name)
            apps.append(app)
    return apps


def list_appimage_apps(appimage_dirs: Sequence[Path] = _APPIMAGE_DIRS) -> list[InstalledApp]:
    """Standalone *.AppImage files in the conventional places people keep
    them — display name is the filename with the extension (and any
    version-number-looking suffix) stripped, launch target is the file
    itself (already executable, no interpreter needed)."""
    seen_names: set[str] = set()
    apps: list[InstalledApp] = []
    for directory in appimage_dirs:
        if not directory.is_dir():
            continue
        for entry_path in sorted(directory.glob("*.AppImage")):
            if not os.access(entry_path, os.X_OK):
                continue
            display_name = entry_path.stem
            if display_name in seen_names:
                continue
            seen_names.add(display_name)
            apps.append(InstalledApp(display_name=display_name, launch_target=str(entry_path), source="appimage"))
    return apps


def _default_path_directories() -> tuple[Path, ...]:
    return tuple(Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)


def list_path_executables(path_directories: Sequence[Path] | None = None) -> list[InstalledApp]:
    """Every executable file in every directory on $PATH — the single
    broadest source of coverage here, since it needs no package-manager
    registration or .desktop file at all: a self-compiled tool the user put
    in ~/bin or ~/.local/bin (exactly why those directories are on PATH in
    the first place), a pip/npm/cargo-installed CLI, and Snap's own bin
    shims (/snap/bin, already on PATH on any system with snapd) are all
    found this way. Noisier than the other sources (thousands of ordinary
    system utilities are also "on PATH"), but modules.app_catalog.matching's
    shortlist step already exists precisely to cut a large candidate pool
    down before it reaches the AI — this only adds more to filter, not a
    new failure mode.

    `path_directories` defaults to parsing the real $PATH; overridable so
    tests don't depend on (or get swamped by) whatever's actually installed
    on the machine running them."""
    directories = path_directories if path_directories is not None else _default_path_directories()
    seen_names: set[str] = set()
    apps: list[InstalledApp] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry_path in entries:
            name = entry_path.name
            if name in seen_names:
                continue
            try:
                if not entry_path.is_file() or not os.access(entry_path, os.X_OK):
                    continue
            except OSError:
                continue
            seen_names.add(name)
            apps.append(InstalledApp(display_name=name, launch_target=name, source="path"))
    return apps


def list_installed_apps(
    desktop_dirs: Sequence[Path] = _DESKTOP_DIRS,
    steam_roots: Sequence[Path] = _STEAM_ROOTS,
    appimage_dirs: Sequence[Path] = _APPIMAGE_DIRS,
    path_directories: Sequence[Path] | None = None,
) -> list[InstalledApp]:
    apps = list_desktop_apps(desktop_dirs)
    for steam_root in steam_roots:
        if steam_root.is_dir():
            apps.extend(list_steam_games(steam_root))
    apps.extend(list_appimage_apps(appimage_dirs))
    apps.extend(list_path_executables(path_directories))
    return apps
