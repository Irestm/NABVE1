from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.os_adapter import screen
from core.os_adapter.base import ActiveWindow, OSAdapter, log_privileged_action

logger = get_logger(__name__)

# Windows Language Identifiers (LCID hex, zero-padded to 8 digits) for
# LoadKeyboardLayoutW — see switch_keyboard_layout below.
_KEYBOARD_LAYOUT_KLID: dict[str, str] = {"ru": "00000419", "uk": "00000422", "en": "00000409"}
# BCP-47 tags for Set-WinUserLanguageList — see change_system_locale below.
_LOCALE_TAGS: dict[str, str] = {"ru": "ru-RU", "uk": "uk-UA", "en": "en-US"}

# ShellExecuteW's "runas" verb return value on failure: values <= 32 are the
# classic SE_ERR_* codes (e.g. 5 = SE_ERR_ACCESSDENIED — the target itself
# refused, not a UAC decision). Declining the UAC consent prompt specifically
# returns 1223 (ERROR_CANCELLED), which is > 32 — a naive "> 32 means
# success" check (an earlier version of this file did exactly that) reads a
# declined prompt as a successful launch. Both must be treated as failure.
_UAC_DECLINED_CODE = 1223


def _shell_execute_runas_failed(result_code: int) -> bool:
    return result_code <= 32 or result_code == _UAC_DECLINED_CODE

_WU_SEARCH_SCRIPT = (
    "$Session = New-Object -ComObject Microsoft.Update.Session; "
    "$Searcher = $Session.CreateUpdateSearcher(); "
    "$Result = $Searcher.Search('IsInstalled=0 and IsHidden=0'); "
    "Write-Output $Result.Updates.Count"
)

# `start` exits almost immediately when it can't find a handler for
# `target` — Popen() succeeding only means cmd.exe itself launched, not that
# `start` actually opened anything. See core/os_adapter/linux.py's identical
# reasoning for xdg-open.
_OPEN_APPLICATION_GRACE_SECONDS = 0.6


class WindowsAdapter(OSAdapter):
    def open_application(self, target: str) -> bool:
        try:
            process = subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        except OSError as exc:
            logger.exception("Failed to open application '%s': %s", target, exc)
            return False

        try:
            return_code = process.wait(timeout=_OPEN_APPLICATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired as still_running:
            logger.debug("'%s' is still running past the grace period, assuming success: %s", target, still_running)
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
        import pygetwindow

        matches = pygetwindow.getWindowsWithTitle(target)
        if not matches:
            return False
        matches[0].close()
        return True

    def shutdown(self) -> None:
        subprocess.run(["shutdown", "/s", "/t", "0"], check=True)

    def restart(self) -> None:
        subprocess.run(["shutdown", "/r", "/t", "0"], check=True)

    def click(self, x: int, y: int, button: str = "left") -> None:
        screen.click(x, y, button)

    def move_mouse(self, x: int, y: int) -> None:
        screen.move_mouse(x, y)

    def type_text(self, text: str) -> None:
        screen.type_text(text)

    def press_key(self, key: str) -> None:
        screen.press_key(key)

    def list_windows(self) -> list[str]:
        import pygetwindow

        return [title for title in pygetwindow.getAllTitles() if title]

    def focus_window(self, title: str) -> bool:
        import pygetwindow

        matches = pygetwindow.getWindowsWithTitle(title)
        if not matches:
            return False
        window = matches[0]
        if window.isMinimized:
            window.restore()
        window.activate()
        return True

    def get_active_window(self) -> ActiveWindow | None:
        import pygetwindow

        window = pygetwindow.getActiveWindow()
        if window is None:
            return None
        # pygetwindow doesn't expose a PID; not needed on this platform
        # anyway, since the AT-SPI-based grounding that consumes it
        # (modules/ui_automation) is Linux-only this round — this method
        # only exists for OSAdapter's per-OS symmetry. bbox is cheap to
        # include (pygetwindow already tracks it) for modules/ui_automation's
        # OCR fallback (see ocr_adapter.py), which works cross-platform.
        return ActiveWindow(
            title=window.title,
            pid=None,
            bbox=(window.left, window.top, window.width, window.height),
        )

    # --- volume ---

    @staticmethod
    def _volume_interface():
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        except ImportError as exc:
            raise RuntimeError(
                "Volume control requires pycaw and comtypes. Install with: pip install pycaw comtypes"
            ) from exc

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self._volume_interface().SetMasterVolumeLevelScalar(percent / 100.0, None)

    def change_volume(self, delta_percent: int) -> None:
        self.set_volume(self.get_volume() + delta_percent)

    def get_volume(self) -> int:
        return round(self._volume_interface().GetMasterVolumeLevelScalar() * 100)

    def mute(self) -> None:
        self._volume_interface().SetMute(1, None)

    def unmute(self) -> None:
        self._volume_interface().SetMute(0, None)

    def toggle_mute(self) -> bool:
        volume = self._volume_interface()
        new_state = not volume.GetMute()
        volume.SetMute(1 if new_state else 0, None)
        return new_state

    # --- windows / tabs ---

    @staticmethod
    def _resolve_window(app_name: str | None):
        import pygetwindow

        if app_name:
            matches = pygetwindow.getWindowsWithTitle(app_name)
            return matches[0] if matches else None
        return pygetwindow.getActiveWindow()

    def hide_window(self, app_name: str | None) -> bool:
        window = self._resolve_window(app_name)
        if window is None:
            return False
        window.minimize()
        return True

    def close_window(self, app_name: str | None) -> bool:
        window = self._resolve_window(app_name)
        if window is None:
            return False
        window.close()
        return True

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
        """Spawns an elevated helper via ShellExecuteW's "runas" verb (which
        triggers the UAC prompt) since the *current* process can't gain admin
        rights mid-run without restarting itself. Waits by polling for the
        path to disappear rather than trusting the exit code alone — the
        elevated child runs asynchronously and ShellExecuteW gives no
        waitable handle in this simple form."""
        if target.is_dir():
            params = f'/c rmdir /s /q "{target}"'
        else:
            params = f'/c del /f /q "{target}"'

        result_code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", params, None, 0)
        if _shell_execute_runas_failed(result_code):
            log_privileged_action(
                "delete_folder", path=str(target), elevation="uac_runas", success=False,
                detail=f"ShellExecuteW returned error code {result_code} (UAC prompt likely declined)",
            )
            raise RuntimeError(
                f"Elevated deletion could not start (ShellExecuteW error {result_code}) — "
                "the UAC prompt may have been declined."
            )

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and target.exists():
            time.sleep(0.5)

        success = not target.exists()
        log_privileged_action(
            "delete_folder", path=str(target), elevation="uac_runas", success=success,
            detail="" if success else "path still exists after elevated delete attempt (timed out after 30s)",
        )
        if not success:
            raise RuntimeError("Удаление с повышенными правами не завершилось за 30 секунд.")
        return {"path": str(target), "deleted": True, "used_elevation": True, "elevation_mechanism": "uac_runas"}

    # --- system language ---

    def switch_keyboard_layout(self, language_code: str) -> dict[str, Any]:
        klid = _KEYBOARD_LAYOUT_KLID.get(language_code)
        if klid is None:
            raise ValueError(f"Неизвестный код языка «{language_code}» для смены раскладки клавиатуры.")

        KLF_ACTIVATE = 0x00000001
        WM_INPUTLANGCHANGEREQUEST = 0x0050

        user32 = ctypes.windll.user32
        hkl = user32.LoadKeyboardLayoutW(klid, KLF_ACTIVATE)
        if not hkl:
            raise RuntimeError(f"LoadKeyboardLayoutW failed for layout {klid}")

        # Changes the layout for whatever window currently has focus, same
        # as the physical Win+Space/Alt+Shift shortcut a user would press —
        # there is no single "system-wide" active layout to set instead.
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        return {"layout": language_code, "klid": klid}

    def change_system_locale(self, language_code: str) -> dict[str, Any]:
        """Requires admin rights (elevated via UAC, see delete_folder's
        docstring for why this uses ShellExecuteW rather than trying to
        elevate the current process) and a logout/restart to fully apply —
        Windows doesn't hot-swap a running session's locale."""
        locale_tag = _LOCALE_TAGS.get(language_code, language_code)
        script = (
            f"$list = New-WinUserLanguageList '{locale_tag}'; Set-WinUserLanguageList $list -Force"
        )
        params = f'-NoProfile -Command "{script}"'

        result_code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 0)
        launched = not _shell_execute_runas_failed(result_code)
        log_privileged_action(
            "change_system_locale", path=None, elevation="uac_runas", success=launched,
            detail=(
                f"launched elevated PowerShell for locale={locale_tag}" if launched
                else f"ShellExecuteW returned error code {result_code} (UAC prompt likely declined)"
            ),
        )
        if not launched:
            raise RuntimeError(
                f"Locale change could not start (ShellExecuteW error {result_code}) — "
                "the UAC prompt may have been declined."
            )
        return {
            "locale": locale_tag,
            "elevation_mechanism": "uac_runas",
            "message": (
                "Смена языка системы запущена с правами администратора. Это подтверждает только "
                "запуск, а не завершение операции. Изменения полностью вступят в силу после выхода "
                "из системы и повторного входа, иногда — после перезагрузки."
            ),
        }

    # --- device / system status ---

    def get_battery_status(self) -> dict[str, Any]:
        import psutil

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
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _WU_SEARCH_SCRIPT],
                capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Проверка обновлений через Windows Update не уложилась в 180 секунд."
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"Windows Update search failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        output_lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        count_line = output_lines[-1] if output_lines else ""
        count = int(count_line) if count_line.isdigit() else None
        return {
            "updates_available": bool(count),
            "count": count,
            "details": f"Доступно обновлений: {count}." if count else "Обновлений нет.",
        }
