#!/usr/bin/env python3
"""Standalone AT-SPI diagnostic — Этап 0 of the plan at
/home/daniil/.claude/plans/effervescent-swimming-sparkle.md.

Not part of the app itself (no imports from core/ or modules/) — this
answers exactly one question: can AT-SPI see a given application's UI tree
at all? Run this and report what it prints BEFORE modules/ui_automation
gets built on top of the assumption that it can — that module deliberately
isn't written yet.

Usage:
    python3 scripts/atspi_smoke_test.py                # list every AT-SPI-visible app
    python3 scripts/atspi_smoke_test.py --active        # dump the tree for the currently focused window
    python3 scripts/atspi_smoke_test.py --pid 12345     # dump the tree for a specific PID

Requires (not installed by default — see requirements.txt / README's
system-packages list):
    sudo apt-get install python3-gi gir1.2-atspi-2.0
If your venv can't `import gi`, recreate it with --system-site-packages, or
`pip install PyGObject` with its native build deps present
(libgirepository1.0-dev libcairo2-dev pkg-config python3-dev).

Also needs:
  - The desktop's accessibility bus enabled — GNOME: Settings ->
    Accessibility, or: gsettings set org.gnome.desktop.interface
    toolkit-accessibility true
  - For JetBrains IDEs specifically (PyCharm): Settings -> Appearance &
    Behavior -> Accessibility -> Support screen readers. This is a
    *separate* toggle from the DE-wide one above — PyCharm's Swing UI
    won't publish an AT-SPI tree without it.

If any AT-SPI/GI call below turns out to have a different exact signature
than assumed (GI bindings can vary a little by distro/version), the
traceback itself is useful diagnostic output — paste it back rather than
trying to fix it blind.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any

_MAX_DEPTH = 6
_MAX_NODES = 200

# Roles worth printing — mirrors the "interactive elements" allowlist
# planned for modules/ui_automation/atspi_adapter.py; container roles like
# panel/frame/scroll pane are structural noise, not clickable targets.
_INTERESTING_ROLES = {
    "push button",
    "menu item",
    "text",
    "entry",
    "check box",
    "radio button",
    "combo box",
    "list item",
    "tab",
    "link",
    "label",
}


def _require_atspi() -> Any:
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        print(
            "Could not import AT-SPI GI bindings. Install them with:\n"
            "  sudo apt-get install python3-gi gir1.2-atspi-2.0\n"
            f"(underlying error: {exc})",
            file=sys.stderr,
        )
        sys.exit(1)
    return Atspi


def _active_window_pid() -> int | None:
    result = subprocess.run(
        ["xdotool", "getactivewindow", "getwindowpid"], capture_output=True, text=True
    )
    text = result.stdout.strip()
    return int(text) if result.returncode == 0 and text.isdigit() else None


def list_apps(atspi: Any) -> None:
    desktop = atspi.get_desktop(0)
    count = desktop.get_child_count()
    print(f"AT-SPI desktop reports {count} registered application(s):\n")
    for index in range(count):
        app = desktop.get_child_at_index(index)
        if app is None:
            continue
        try:
            pid = app.get_process_id()
        except Exception as exc:  # noqa: BLE001 — diagnostic script, print and continue
            pid = f"<error: {exc}>"
        try:
            name = app.get_name()
        except Exception as exc:  # noqa: BLE001
            name = f"<error: {exc}>"
        print(f"  pid={pid!s:>10}  name={name!r}")


def _extents(atspi: Any, node: Any) -> tuple[int, int, int, int] | None:
    try:
        component = node.get_component_iface()
    except Exception:
        return None
    if component is None:
        return None
    try:
        extents = component.get_extents(atspi.CoordType.SCREEN)
        return (extents.x, extents.y, extents.width, extents.height)
    except Exception:
        return None


def _walk(atspi: Any, node: Any, depth: int, printed: list[int]) -> None:
    if depth > _MAX_DEPTH or printed[0] >= _MAX_NODES:
        return
    try:
        role = node.get_role_name()
        name = node.get_name()
    except Exception:
        return

    if role in _INTERESTING_ROLES and name:
        bbox = _extents(atspi, node)
        print(f"{'  ' * depth}[{role}] {name!r} bbox={bbox}")
        printed[0] += 1

    try:
        child_count = node.get_child_count()
    except Exception:
        return
    for index in range(child_count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            _walk(atspi, child, depth + 1, printed)


def dump_tree(atspi: Any, pid: int) -> None:
    desktop = atspi.get_desktop(0)
    target = None
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if app is None:
            continue
        try:
            if app.get_process_id() == pid:
                target = app
                break
        except Exception:
            continue

    if target is None:
        print(f"No AT-SPI application entry found for pid={pid}.")
        print(
            "This means AT-SPI cannot see this app's UI at all — for JetBrains IDEs, check "
            "Settings -> Appearance & Behavior -> Accessibility -> Support screen readers, "
            "and make sure the DE's accessibility bus is enabled."
        )
        return

    print(
        f"Found application: {target.get_name()!r} (pid={pid}). Walking its tree "
        f"(interactive roles only, max depth {_MAX_DEPTH}, max {_MAX_NODES} nodes):\n"
    )
    printed = [0]
    _walk(atspi, target, 0, printed)
    if printed[0] == 0:
        print(
            "(nothing matched — the app IS registered on the AT-SPI bus, but its tree is "
            "empty or has no elements with the roles this script looks for; this is the "
            "'patchy Swing/JetBrains accessibility support' failure mode called out in the plan)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pid", type=int, help="dump the element tree for this PID")
    parser.add_argument(
        "--active",
        action="store_true",
        help="resolve the currently active window's PID via xdotool, then dump its tree",
    )
    args = parser.parse_args()

    atspi = _require_atspi()

    if args.active:
        pid = _active_window_pid()
        if pid is None:
            print(
                "Could not resolve the active window's PID via xdotool "
                "(is it installed? sudo apt-get install xdotool).",
                file=sys.stderr,
            )
            sys.exit(1)
        dump_tree(atspi, pid)
    elif args.pid is not None:
        dump_tree(atspi, args.pid)
    else:
        list_apps(atspi)


if __name__ == "__main__":
    main()
