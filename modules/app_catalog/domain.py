from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstalledApp:
    """A single installed application or game found on this machine (see
    modules/app_catalog/{linux,windows}.py). `launch_target` is already in
    the shape core.os_adapter's `OSAdapter.open_application(target)` expects
    for whichever `source` produced it — a bare executable name for a Linux
    .desktop entry, a steam:// URI for a Steam game on either OS (Steam
    itself registers that protocol handler with the OS), or a .lnk shortcut
    path on Windows (which `start` resolves natively) — so a caller never
    needs to branch on `source` before launching."""

    display_name: str
    launch_target: str
    source: str  # "desktop" | "steam" | "shortcut" - diagnostic only for now
