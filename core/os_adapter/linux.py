from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

from core.logger import get_logger
from core.os_adapter import screen
from core.os_adapter.base import ActiveWindow, OSAdapter, log_privileged_action

logger = get_logger(__name__)

# hide_window/close_window(app_name=None) and switch_keyboard_layout below
# rely on wmctrl/xdotool/setxkbmap, all of which are X11-native tools. Under
# a Wayland compositor they work only through XWayland — i.e. only against
# other XWayland (X11-compat) clients, never against native Wayland windows
# — and most Wayland compositors deliberately don't let any client query or
# control *other* clients' windows for security reasons, with no portable
# replacement API. GNOME/KDE users on Wayland should expect hide_window/
# close_window(app_name=None) and switch_keyboard_layout's setxkbmap path to
# simply fail; switch_keyboard_layout falls back to gsettings (GNOME-only)
# in that case. This is a real platform limitation, not a bug in this file.
_VOLUME_TOOL_INSTALL_HINT = (
    "Volume control requires pactl (PulseAudio/PipeWire) or amixer (ALSA). "
    "Install with: sudo apt-get install pulseaudio-utils"
)
_PERCENT_RE = re.compile(r"(\d+)%")

# brightnessctl drives the real backlight without root (it talks to logind);
# xrandr is a fallback that only applies a software gamma ramp on the primary
# output (no backlight change) but always works under X11 with no extra
# package. Neither exists under a bare Wayland session with no compositor
# helper — same platform caveat as the wmctrl/xdotool tools above.
_BRIGHTNESS_TOOL_INSTALL_HINT = (
    "Brightness control requires brightnessctl or xrandr. "
    "Install with: sudo apt-get install brightnessctl"
)
# Never let a voice command drop the screen to an unreadable level it would
# then be impossible to raise back by looking at the screen.
_MIN_BRIGHTNESS_PERCENT = 5
_XRANDR_BRIGHTNESS_RE = re.compile(r"Brightness:\s*([\d.]+)")

# Ordered most-portable-first: loginctl (systemd-logind) locks the seat on
# nearly every modern desktop regardless of DE or X11/Wayland; the rest are
# narrower fallbacks for setups without a working logind lock.
_SCREEN_LOCK_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("loginctl", "lock-session"),
    ("gnome-screensaver-command", "-l"),
    ("xdg-screensaver", "lock"),
)
_SCREEN_LOCK_INSTALL_HINT = (
    "Screen locking needs one of: loginctl (systemd), gnome-screensaver-command, "
    "or xdg-screensaver. None is available on this system."
)

_KEYBOARD_LAYOUT_CODES: dict[str, str] = {"ru": "ru", "uk": "ua", "en": "us"}
_LOCALE_CODES: dict[str, str] = {"ru": "ru_RU.UTF-8", "uk": "uk_UA.UTF-8", "en": "en_US.UTF-8"}

_ELEVATED_COMMAND_TIMEOUT_SECONDS = 120


def _current_xkb_layouts() -> list[str]:
    """Returns the X server's current XKB layout list (e.g. ["us", "ru", "ua", "ru"]
    for `setxkbmap -query`'s "layout: us,ru,ua,ru" line), or [] if it can't be
    read — switch_keyboard_layout below falls back to a single-layout switch
    in that case, same as before this existed."""
    try:
        result = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True)
    except OSError:
        return []
    if result.returncode != 0:
        return []
    for line in result.stdout.splitlines():
        if line.startswith("layout:"):
            return [item.strip() for item in line.split(":", 1)[1].split(",") if item.strip()]
    return []


def _run_elevated(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Runs a pkexec/sudo-prefixed command. stdin is explicitly closed
    (DEVNULL) rather than left inherited from this backend process — sudo
    without a usable terminal/askpass helper would otherwise block
    indefinitely waiting for a password that can never arrive, instead of
    failing fast the way pkexec's own GUI polkit prompt does. A generous
    timeout still bounds pkexec's GUI prompt (the user needs time to see and
    respond to it) without risking an unbounded hang either way."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=_ELEVATED_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="",
            stderr=f"Timed out after {_ELEVATED_COMMAND_TIMEOUT_SECONDS}s waiting for elevated command",
        )

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
        except ValueError as unbalanced_quoting:
            logger.debug("Could not shlex-split target '%s': %s", target, unbalanced_quoting, exc_info=True)
            tokens = []
        if tokens and shutil.which(tokens[0]):
            return tokens
    return ["xdg-open", target]


class LinuxAdapter(OSAdapter):
    def open_application(self, target: str) -> bool:
        try:
            process = subprocess.Popen(_resolve_launch_argv(target))
        except OSError as exc:
            logger.exception("Failed to open application '%s': %s", target, exc)
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

    # --- volume ---

    @staticmethod
    def _volume_backend() -> str:
        if shutil.which("pactl"):
            return "pactl"
        if shutil.which("amixer"):
            return "amixer"
        raise RuntimeError(_VOLUME_TOOL_INSTALL_HINT)

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        backend = self._volume_backend()
        if backend == "pactl":
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"], check=True)
        else:
            subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{percent}%"], check=True)

    def change_volume(self, delta_percent: int) -> None:
        self.set_volume(self.get_volume() + delta_percent)

    def get_volume(self) -> int:
        backend = self._volume_backend()
        if backend == "pactl":
            output = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, check=True
            ).stdout
        else:
            output = subprocess.run(
                ["amixer", "get", "Master"], capture_output=True, text=True, check=True
            ).stdout
        match = _PERCENT_RE.search(output)
        if not match:
            raise RuntimeError(f"Could not parse volume from {backend} output")
        return int(match.group(1))

    def _set_mute(self, muted: bool) -> None:
        backend = self._volume_backend()
        if backend == "pactl":
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"], check=True)
        else:
            subprocess.run(["amixer", "set", "Master", "mute" if muted else "unmute"], check=True)

    def mute(self) -> None:
        self._set_mute(True)

    def unmute(self) -> None:
        self._set_mute(False)

    def toggle_mute(self) -> bool:
        backend = self._volume_backend()
        if backend == "pactl":
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=True)
            output = subprocess.run(
                ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], capture_output=True, text=True, check=True
            ).stdout
            return "yes" in output.lower()
        output = subprocess.run(
            ["amixer", "set", "Master", "toggle"], capture_output=True, text=True, check=True
        ).stdout
        return "[off]" in output.lower()

    # --- brightness ---

    def _brightness_backend(self) -> str:
        # Sticky downgrade: once a brightnessctl write has failed on permission
        # (user not in the "video" group / no udev uaccess), stay on xrandr for
        # the rest of this process so get and set never straddle two backends
        # with unrelated scales. Reset naturally on the next app start.
        if not getattr(self, "_brightness_force_xrandr", False) and shutil.which("brightnessctl"):
            return "brightnessctl"
        if shutil.which("xrandr"):
            return "xrandr"
        if shutil.which("brightnessctl"):
            return "brightnessctl"
        raise RuntimeError(_BRIGHTNESS_TOOL_INSTALL_HINT)

    @staticmethod
    def _primary_xrandr_output() -> str:
        query = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, check=True
        ).stdout
        connected = [line for line in query.splitlines() if " connected" in line]
        for line in connected:
            if " connected primary" in line:
                return line.split()[0]
        if connected:
            return connected[0].split()[0]
        raise RuntimeError("xrandr reports no connected display")

    def _set_brightness_xrandr(self, percent: int) -> None:
        subprocess.run(
            ["xrandr", "--output", self._primary_xrandr_output(), "--brightness", f"{percent / 100:.2f}"],
            check=True,
        )

    def set_brightness(self, percent: int) -> None:
        percent = max(_MIN_BRIGHTNESS_PERCENT, min(100, percent))
        if self._brightness_backend() == "brightnessctl":
            try:
                subprocess.run(["brightnessctl", "set", f"{percent}%"], check=True, capture_output=True)
                return
            except subprocess.CalledProcessError:
                if not shutil.which("xrandr"):
                    raise
                logger.warning(
                    "brightnessctl could not set the backlight (permission denied). Falling back to "
                    "xrandr software gamma. For real backlight control add your user to the 'video' "
                    "group ('sudo usermod -aG video $USER') and log out and back in."
                )
                self._brightness_force_xrandr = True
        self._set_brightness_xrandr(percent)

    def change_brightness(self, delta_percent: int) -> None:
        self.set_brightness(self.get_brightness() + delta_percent)

    def get_brightness(self) -> int:
        if self._brightness_backend() == "brightnessctl":
            output = subprocess.run(
                ["brightnessctl", "-m"], capture_output=True, text=True, check=True
            ).stdout
            match = _PERCENT_RE.search(output)
            if not match:
                raise RuntimeError("Could not parse brightness from brightnessctl output")
            return int(match.group(1))
        output = subprocess.run(
            ["xrandr", "--verbose"], capture_output=True, text=True, check=True
        ).stdout
        match = _XRANDR_BRIGHTNESS_RE.search(output)
        if not match:
            raise RuntimeError("Could not parse brightness from xrandr output")
        return round(float(match.group(1)) * 100)

    # --- media ---

    def pause_media(self) -> list[str]:
        # playerctl speaks MPRIS, so this covers browsers (YouTube), Spotify,
        # VLC, mpv, ... — anything exposing a standard media interface. No
        # playerctl -> nothing we can do, but a reminder must not fail over
        # it, so return [] rather than raising.
        if not shutil.which("playerctl"):
            logger.info("pause_media: playerctl not installed, nothing paused")
            return []
        listing = subprocess.run(
            ["playerctl", "--list-all"], capture_output=True, text=True
        )
        if listing.returncode != 0:
            return []
        paused: list[str] = []
        for player in (line.strip() for line in listing.stdout.splitlines() if line.strip()):
            status = subprocess.run(
                ["playerctl", "--player", player, "status"], capture_output=True, text=True
            )
            if status.returncode == 0 and status.stdout.strip().lower() == "playing":
                if subprocess.run(
                    ["playerctl", "--player", player, "pause"], capture_output=True, text=True
                ).returncode == 0:
                    paused.append(player)
        return paused

    def resume_media(self, tokens: list[str]) -> None:
        if not tokens or not shutil.which("playerctl"):
            return
        for player in tokens:
            subprocess.run(
                ["playerctl", "--player", player, "play"], capture_output=True, text=True
            )

    # --- session ---

    def lock_screen(self) -> None:
        for command in _SCREEN_LOCK_COMMANDS:
            if not shutil.which(command[0]):
                continue
            result = subprocess.run(list(command), capture_output=True, text=True)
            if result.returncode == 0:
                return
            logger.warning(
                "Screen lock via '%s' failed (code %s): %s — trying next backend",
                command[0], result.returncode, result.stderr.strip() or result.stdout.strip(),
            )
        raise RuntimeError(_SCREEN_LOCK_INSTALL_HINT)

    # --- windows / tabs ---

    def hide_window(self, app_name: str | None) -> bool:
        # See the Wayland caveat comment at the top of this file.
        if app_name:
            _require_wmctrl()
            result = subprocess.run(
                ["wmctrl", "-r", app_name, "-b", "add,hidden"], capture_output=True, text=True
            )
            return result.returncode == 0
        _require_xdotool()
        result = subprocess.run(
            ["xdotool", "getactivewindow", "windowminimize"], capture_output=True, text=True
        )
        return result.returncode == 0

    def close_window(self, app_name: str | None) -> bool:
        if app_name:
            return self.close_application(app_name)
        _require_xdotool()
        result = subprocess.run(
            ["xdotool", "getactivewindow", "windowclose"], capture_output=True, text=True
        )
        return result.returncode == 0

    def close_tab(self) -> None:
        screen.hotkey("ctrl", "w")

    # --- filesystem ---

    def create_folder(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        if target.exists():
            return {"path": str(target), "created": False, "message": f"Папка уже существует: {target}"}
        target.mkdir(parents=True, exist_ok=True)
        return {"path": str(target), "created": True}

    def move_folder(self, source: str, destination: str) -> dict[str, Any]:
        src = Path(source).expanduser()
        dst = Path(destination).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"Источник не найден: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        result_path = shutil.move(str(src), str(dst))
        return {"source": str(src), "destination": str(result_path)}

    def delete_folder(self, path: str, force_admin: bool = False) -> dict[str, Any]:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"Путь не найден: {target}")
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except PermissionError:
            if not force_admin:
                log_privileged_action(
                    "delete_folder", path=str(target), elevation=None, success=False,
                    detail="PermissionError and force_admin was not set",
                )
                raise
            return self._delete_folder_elevated(target)
        log_privileged_action("delete_folder", path=str(target), elevation=None, success=True)
        return {"path": str(target), "deleted": True, "used_elevation": False}

    @staticmethod
    def _delete_folder_elevated(target: Path) -> dict[str, Any]:
        if shutil.which("pkexec"):
            cmd, mechanism = ["pkexec", "rm", "-rf", "--", str(target)], "pkexec"
        elif shutil.which("sudo"):
            cmd, mechanism = ["sudo", "rm", "-rf", "--", str(target)], "sudo"
        else:
            log_privileged_action(
                "delete_folder", path=str(target), elevation=None, success=False,
                detail="neither pkexec nor sudo is available",
            )
            raise RuntimeError("Elevated deletion requires pkexec or sudo, neither is available.")

        result = _run_elevated(cmd)
        success = result.returncode == 0 and not target.exists()
        log_privileged_action(
            "delete_folder", path=str(target), elevation=mechanism, success=success,
            detail="" if success else (result.stderr.strip() or "unknown error"),
        )
        if not success:
            raise RuntimeError(f"Elevated deletion failed: {result.stderr.strip() or 'unknown error'}")
        return {"path": str(target), "deleted": True, "used_elevation": True, "elevation_mechanism": mechanism}

    # --- system language ---

    def switch_keyboard_layout(self, language_code: str) -> dict[str, Any]:
        layout = _KEYBOARD_LAYOUT_CODES.get(language_code, language_code)
        if shutil.which("setxkbmap"):
            # Passing just `layout` here would silently replace the user's
            # whole configured layout list (e.g. a us/ru/ua set toggled via a
            # hotkey) with that one language, breaking the toggle until they
            # reconfigure it by hand. Reorder the existing list instead so the
            # requested layout becomes active (group 0) while the rest stay
            # available; falls back to a plain single-layout switch if the
            # current list can't be read (_current_xkb_layouts() returns []).
            existing = _current_xkb_layouts()
            ordered = [layout] + [item for item in existing if item != layout]
            target_arg = ",".join(ordered)
            result = subprocess.run(["setxkbmap", target_arg], capture_output=True, text=True)
            if result.returncode == 0:
                return {"layout": layout, "backend": "setxkbmap"}
            # Falls through to gsettings below — e.g. setxkbmap has nothing to
            # talk to under a pure-Wayland session (see the caveat comment at
            # the top of this file).
        if shutil.which("gsettings"):
            source = f"[('xkb','{layout}')]"
            result = subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.input-sources", "sources", source],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return {
                    "layout": layout,
                    "backend": "gsettings",
                    "message": (
                        "Раскладка переключена через gsettings (GNOME). Это заменяет весь список "
                        "источников ввода на один — остальные ранее настроенные раскладки сброшены."
                    ),
                }
            raise RuntimeError(f"gsettings failed: {result.stderr.strip()}")
        raise RuntimeError(
            "Keyboard layout switching requires setxkbmap (X11) or gsettings (GNOME). Neither is "
            "available, or this is a non-GNOME Wayland compositor — see this file's Wayland caveat."
        )

    def change_system_locale(self, language_code: str) -> dict[str, Any]:
        locale = _LOCALE_CODES.get(language_code, language_code)
        if not shutil.which("localectl"):
            raise RuntimeError("System locale change requires localectl (systemd).")

        if shutil.which("pkexec"):
            cmd, mechanism = ["pkexec", "localectl", "set-locale", f"LANG={locale}"], "pkexec"
        elif shutil.which("sudo"):
            cmd, mechanism = ["sudo", "localectl", "set-locale", f"LANG={locale}"], "sudo"
        else:
            cmd, mechanism = ["localectl", "set-locale", f"LANG={locale}"], None

        result = _run_elevated(cmd) if mechanism else subprocess.run(cmd, capture_output=True, text=True)
        success = result.returncode == 0
        log_privileged_action(
            "change_system_locale", path=None, elevation=mechanism, success=success,
            detail=locale if success else (result.stderr.strip() or "unknown error"),
        )
        if not success:
            raise RuntimeError(f"Locale change failed: {result.stderr.strip() or 'unknown error'}")
        return {
            "locale": locale,
            "elevation_mechanism": mechanism,
            "message": "Локаль изменена. Полностью изменения вступят в силу после перезахода в систему.",
        }

    # --- device / system status ---

    def get_battery_status(self) -> dict[str, Any]:
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "percent": None,
                "time_remaining_minutes": None,
                "is_charging": None,
                "message": "На этом устройстве нет батареи.",
            }
        time_remaining: int | None = None
        if battery.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
            time_remaining = battery.secsleft // 60
        return {
            "percent": int(battery.percent),
            "time_remaining_minutes": time_remaining,
            "is_charging": battery.power_plugged,
        }

    def check_system_updates(self) -> dict[str, Any]:
        if shutil.which("apt"):
            return self._check_updates_apt()
        if shutil.which("dnf"):
            return self._check_updates_dnf()
        if shutil.which("pacman"):
            return self._check_updates_pacman()
        return {
            "updates_available": False,
            "count": None,
            "details": "Не удалось определить пакетный менеджер (нужен apt, dnf или pacman).",
        }

    @staticmethod
    def _check_updates_apt() -> dict[str, Any]:
        # Reads apt's current package index as-is — does not run `apt-get
        # update` first (that needs root and network, and silently doing it
        # on every check would be a surprising side effect of a status query).
        # Results reflect whenever the index was last refreshed.
        result = subprocess.run(
            ["apt", "list", "--upgradable"], capture_output=True, text=True, timeout=60
        )
        lines = [line for line in result.stdout.splitlines() if line and not line.startswith("Listing...")]
        count = len(lines)
        return {
            "updates_available": count > 0,
            "count": count,
            "details": f"Доступно обновлений: {count}." if count else "Обновлений нет.",
        }

    @staticmethod
    def _check_updates_dnf() -> dict[str, Any]:
        # dnf check-update's exit code IS the signal: 100 = updates available,
        # 0 = none, anything else = a real error.
        result = subprocess.run(["dnf", "check-update"], capture_output=True, text=True, timeout=120)
        if result.returncode not in (0, 100):
            raise RuntimeError(f"dnf check-update failed: {result.stderr.strip() or result.stdout.strip()}")
        lines = [
            line for line in result.stdout.splitlines()
            if line.strip() and not line.startswith(("Last metadata", "Obsoleting"))
        ]
        count = len(lines) if result.returncode == 100 else 0
        return {
            "updates_available": result.returncode == 100,
            "count": count,
            "details": f"Доступно обновлений: {count}." if count else "Обновлений нет.",
        }

    @staticmethod
    def _check_updates_pacman() -> dict[str, Any]:
        # Checks against the local sync database as-is (no -Sy refresh —
        # same "don't silently touch package state from a status query"
        # reasoning as _check_updates_apt above).
        result = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True, timeout=60)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        count = len(lines)
        return {
            "updates_available": count > 0,
            "count": count,
            "details": f"Доступно обновлений: {count}." if count else "Обновлений нет.",
        }
