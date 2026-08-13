from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.vdf import find_all_values, find_value, parse_vdf

logger = get_logger(__name__)


def _library_paths(steam_root: Path) -> list[Path]:
    """Every Steam library folder that might hold installed games: the
    client's own install dir always counts as one (steamapps/ lives there
    directly), plus whatever additional libraries libraryfolders.vdf lists
    (external drives, second SSD, ...)."""
    libraries = [steam_root]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries

    try:
        data = parse_vdf(text)
    except ValueError:
        logger.warning("Failed to parse %s; only the main Steam library will be scanned", vdf_path, exc_info=True)
        return libraries

    for raw_path in find_all_values(data, "path"):
        path = Path(raw_path)
        if path not in libraries:
            libraries.append(path)
    return libraries


def list_steam_games(steam_root: Path) -> list[InstalledApp]:
    """Installed Steam games under `steam_root` (the Steam *client's* own
    install directory — e.g. ~/.steam/steam on Linux, the SteamPath registry
    value on Windows — not a game's own folder) and any additional libraries
    it references.

    Launch target is the same steam:// URI on every OS Steam supports,
    since Steam itself registers that protocol handler with the OS — see
    core/os_adapter/{linux,windows}.py's open_application, which already
    knows how to hand a URI to the OS. No Steam-specific launch code is
    needed on our side beyond producing this string."""
    apps: list[InstalledApp] = []
    for library in _library_paths(steam_root):
        steamapps_dir = library / "steamapps"
        if not steamapps_dir.is_dir():
            continue
        for manifest_path in sorted(steamapps_dir.glob("appmanifest_*.acf")):
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                data = parse_vdf(text)
            except ValueError:
                logger.debug("Failed to parse Steam manifest %s", manifest_path, exc_info=True)
                continue

            appid = find_value(data, "appid")
            name = find_value(data, "name")
            if not appid or not name:
                continue
            apps.append(
                InstalledApp(display_name=name, launch_target=f"steam://rungameid/{appid}", source="steam")
            )
    return apps
