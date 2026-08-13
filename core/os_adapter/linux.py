from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from core.logger import get_logger
from core.os_adapter import screen
from core.os_adapter.base import ActiveWindow, OSAdapter

logger = get_logger(__name__)

# xdg-open (and some direct executables that fail fast — e.g. a missing
# shared library) exits almost immediately when it can't do anything with
# `target` — Popen() succeeding only means the OS could fork/exec the
# process, not that it actually opened anything. This grace window catches
# that class of failure without blocking on a real GUI app's entire
# lifetime, which we don't want to wait for at all.
_OPEN_APPLICATION_GRACE_SECONDS = 0.6


def _require_wmctrl() -> None:
    if not shutil.which("wmctrl"):
        raise RuntimeError(
            "Window management requires wmctrl. Install it with: sudo apt-get install wmctrl"
        )


def _require_xdotool() -> None:
    if not shutil.which("xdotool"):
        raise RuntimeError(
            "Active-window detection requires xdotool. Install it with: sudo apt-get install xdotool"
        )


def _resolve_launch_argv(target: str) -> list[str]:
    """The argv to actually exec for `target`: itself, if it's already a
    valid single executable/path (covers the common case, including a path
    that happens to contain a space — checked as one whole string, never
    split); split into a real argv if it's a multi-word shell command whose
    first word is itself a valid executable (currently only produced by
    modules/app_catalog/linux.py for Flatpak apps — "flatpak run
    org.telegram.desktop", since a Flatpak-exported .desktop's Exec line
    can't be reduced to one bare token the way a normal app's can); or
    handed to xdg-open as-is otherwise (a URL, a steam:// URI, or a target
    with no better interpretation)."""
    if shutil.which(target):
        return [target]
    if " " in target:
        try:
            tokens = shlex.split(target)
        except ValueError:
            tokens = []
        if tokens and shutil.which(tokens[0]):
            return tokens
    return ["xdg-open", target]


class LinuxAdapter(OSAdapter):
    def open_application(self, target: str) -> bool:
        try:
            process = subprocess.Popen(_resolve_launch_argv(target))
        except OSError as exc:
            logger.error("Failed to open application '%s': %s", target, exc)
            return False

        # Without this check, a target xdg-open has no handler for (a typo'd
        # app name, an app that isn't actually installed, a garbled voice
        # transcription) silently "succeeded" — Popen() never raises just
        # because the child process it launched (xdg-open itself) went on to
        # fail on its own a moment later. That was reported back as "Готово"
        # even though nothing opened.
        try:
            return_code = process.wait(timeout=_OPEN_APPLICATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return True
        if return_code != 0:
            logger.error(
                "Application '%s' exited immediately with code %s — likely no handler or not found",
                target,
                return_code,
            )
            return False
        return True

    def close_application(self, target: str) -> bool:
        # wmctrl -c already does a substring match against open window
        # titles (same as focus_window's -a) and asks the window to close
        # gracefully via WM_DELETE_WINDOW rather than killing the process,
        # so a well-behaved app gets to save state/prompt before exiting.
        _require_wmctrl()
        result = subprocess.run(["wmctrl", "-c", target], capture_output=True, text=True)
        return result.returncode == 0

    def shutdown(self) -> None:
        self._power_action("poweroff", "-h")

    def restart(self) -> None:
        self._power_action("reboot", "-r")

    @staticmethod
    def _power_action(systemctl_verb: str, shutdown_flag: str) -> None:
        # `shutil.which`/bare `subprocess.run(["shutdown", ...])` rely on
        # $PATH, which under some launch contexts (desktop session services,
        # IDE run configs) doesn't include /usr/sbin where `shutdown` lives
        # on Debian/Ubuntu — that produced a bare, unhelpful
        # "FileNotFoundError: [Errno 2] No such file or directory: 'shutdown'"
        # in production. Try systemctl by PATH, then `shutdown` by PATH, then
        # both by their standard absolute locations before giving up.
        systemctl = shutil.which("systemctl")
        if systemctl:
            subprocess.run([systemctl, systemctl_verb], check=True)
            return

        shutdown_bin = shutil.which("shutdown")
        for candidate in filter(None, [shutdown_bin, "/usr/sbin/shutdown", "/sbin/shutdown"]):
            if candidate == shutdown_bin or Path(candidate).exists():
                subprocess.run([candidate, shutdown_flag, "now"], check=True)
                return

        raise RuntimeError(
            "Neither 'systemctl' nor 'shutdown' could be found (checked $PATH and "
            "/usr/sbin, /sbin). Power actions are unavailable on this system."
        )

    def click(self, x: int, y: int, button: str = "left") -> None:
        screen.click(x, y, button)

    def move_mouse(self, x: int, y: int) -> None:
        screen.move_mouse(x, y)

    def type_text(self, text: str) -> None:
        screen.type_text(text)

    def press_key(self, key: str) -> None:
        screen.press_key(key)

    def list_windows(self) -> list[str]:
        _require_wmctrl()
        output = subprocess.run(
            ["wmctrl", "-l"], check=True, capture_output=True, text=True
        ).stdout
        titles: list[str] = []
        for line in output.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                titles.append(parts[3])
        return titles

    def focus_window(self, title: str) -> bool:
        _require_wmctrl()
        result = subprocess.run(["wmctrl", "-a", title], capture_output=True, text=True)
        return result.returncode == 0

    def get_active_window(self) -> ActiveWindow | None:
        # wmctrl -l lists every window but never marks which one is focused —
        # xdotool is the tool that actually answers "what's active right now".
        _require_xdotool()
        name_result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True
        )
        if name_result.returncode != 0:
            return None

        pid_result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid"], capture_output=True, text=True
        )
        pid_text = pid_result.stdout.strip()
        pid = int(pid_text) if pid_result.returncode == 0 and pid_text.isdigit() else None

        class_result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowclassname"], capture_output=True, text=True
        )
        wm_class = class_result.stdout.strip() if class_result.returncode == 0 else None

        # --shell prints KEY=VALUE lines (X, Y, WIDTH, HEIGHT among them) —
        # used by modules/ui_automation/ocr_adapter.py to screenshot just
        # this window instead of the whole desktop. Best-effort: any
        # unexpected output just leaves bbox as None, same as a tool that
        # isn't installed.
        geometry_result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
            capture_output=True, text=True,
        )
        bbox: tuple[int, int, int, int] | None = None
        if geometry_result.returncode == 0:
            geometry: dict[str, int] = {}
            for line in geometry_result.stdout.splitlines():
                key, _, value = line.partition("=")
                value = value.strip()
                if key in ("X", "Y", "WIDTH", "HEIGHT") and value.lstrip("-").isdigit():
                    geometry[key] = int(value)
            if {"X", "Y", "WIDTH", "HEIGHT"} <= geometry.keys():
                bbox = (geometry["X"], geometry["Y"], geometry["WIDTH"], geometry["HEIGHT"])

        return ActiveWindow(
            title=name_result.stdout.strip(), pid=pid, wm_class=wm_class or None, bbox=bbox
        )
