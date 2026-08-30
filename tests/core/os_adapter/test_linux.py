from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from core.os_adapter.base import ActiveWindow
from core.os_adapter.linux import LinuxAdapter, _resolve_launch_argv


def _fake_process(return_code: int) -> MagicMock:
    process = MagicMock()
    process.wait.return_value = return_code
    return process


def test_open_application_succeeds_when_process_keeps_running(monkeypatch) -> None:
    # A real GUI app is still starting up (or just running) past the grace
    # window - wait() times out rather than returning, which must count as
    # success, not failure.
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    process = MagicMock()
    process.wait.side_effect = subprocess.TimeoutExpired(cmd="xdg-open", timeout=0.6)
    monkeypatch.setattr("core.os_adapter.linux.subprocess.Popen", lambda *a, **k: process)

    assert LinuxAdapter().open_application("firefox") is True


def test_open_application_fails_when_xdg_open_exits_immediately_with_error(monkeypatch) -> None:
    # Regression: this used to report success just because Popen() itself
    # didn't raise, even though the xdg-open process it launched went on to
    # fail (no handler for a garbled/nonexistent target) a moment later.
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    monkeypatch.setattr("core.os_adapter.linux.subprocess.Popen", lambda *a, **k: _fake_process(3))

    assert LinuxAdapter().open_application("телеграм") is False


def test_open_application_succeeds_when_direct_executable_exits_cleanly(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/true")
    monkeypatch.setattr("core.os_adapter.linux.subprocess.Popen", lambda *a, **k: _fake_process(0))

    assert LinuxAdapter().open_application("true") is True


def test_open_application_fails_when_direct_executable_exits_with_error(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/false")
    monkeypatch.setattr("core.os_adapter.linux.subprocess.Popen", lambda *a, **k: _fake_process(1))

    assert LinuxAdapter().open_application("false") is False


def test_open_application_returns_false_when_popen_itself_raises(monkeypatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("no such file")

    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    monkeypatch.setattr("core.os_adapter.linux.subprocess.Popen", _raise)

    assert LinuxAdapter().open_application("does-not-exist") is False


# --- close_application ------------------------------------------------------


def test_close_application_succeeds_when_wmctrl_finds_a_matching_window(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/wmctrl")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run", lambda *a, **k: MagicMock(returncode=0)
    )

    assert LinuxAdapter().close_application("Telegram") is True


def test_close_application_fails_when_no_window_matches(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/wmctrl")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run", lambda *a, **k: MagicMock(returncode=1)
    )

    assert LinuxAdapter().close_application("no such window") is False


# --- _resolve_launch_argv --------------------------------------------------


def test_resolve_launch_argv_direct_executable(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: name if name == "steam" else None)
    assert _resolve_launch_argv("steam") == ["steam"]


def test_resolve_launch_argv_path_with_space_is_not_split(monkeypatch) -> None:
    # A real file whose path happens to contain a space must be treated as
    # ONE argument, not shell-split into two bogus tokens.
    target = "/opt/my app/bin/run"
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: name if name == target else None)
    assert _resolve_launch_argv(target) == [target]


def test_resolve_launch_argv_flatpak_multiword_command(monkeypatch) -> None:
    # modules/app_catalog/linux.py produces exactly this shape for a
    # Flatpak-installed app's resolved launch_target.
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: name if name == "flatpak" else None)
    assert _resolve_launch_argv("flatpak run org.telegram.desktop") == ["flatpak", "run", "org.telegram.desktop"]


def test_resolve_launch_argv_falls_back_to_xdg_open_for_a_url(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    url = "https://example.com/some?query=with spaces"
    assert _resolve_launch_argv(url) == ["xdg-open", url]


def test_resolve_launch_argv_falls_back_when_multiword_first_token_is_not_executable(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    target = "не открывается ничего"
    assert _resolve_launch_argv(target) == ["xdg-open", target]


# --- get_active_window -------------------------------------------------------


def _xdotool_side_effect(
    name_stdout: str,
    name_rc: int,
    pid_stdout: str,
    pid_rc: int,
    class_stdout: str = "",
    class_rc: int = 0,
    # Failing by default (rc=1) so existing callers that don't care about
    # geometry get bbox=None, same as before this subcommand existed.
    geometry_stdout: str = "",
    geometry_rc: int = 1,
):
    def _run(args, **_kwargs):
        if "getwindowgeometry" in args:
            return MagicMock(returncode=geometry_rc, stdout=geometry_stdout)
        subcommand = args[-1]
        if subcommand == "getwindowname":
            return MagicMock(returncode=name_rc, stdout=name_stdout)
        if subcommand == "getwindowpid":
            return MagicMock(returncode=pid_rc, stdout=pid_stdout)
        assert subcommand == "getwindowclassname"
        return MagicMock(returncode=class_rc, stdout=class_stdout)

    return _run


def test_get_active_window_requires_xdotool(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    try:
        LinuxAdapter().get_active_window()
    except RuntimeError as exc:
        assert "xdotool" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_get_active_window_returns_none_when_xdotool_fails(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run", _xdotool_side_effect("", 1, "", 1)
    )

    assert LinuxAdapter().get_active_window() is None


def test_get_active_window_returns_title_pid_and_wm_class_on_success(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        _xdotool_side_effect("PyCharm — assistant\n", 0, "12345\n", 0, "jetbrains-pycharm\n", 0),
    )

    assert LinuxAdapter().get_active_window() == ActiveWindow(
        title="PyCharm — assistant", pid=12345, wm_class="jetbrains-pycharm"
    )


def test_get_active_window_pid_none_when_pid_lookup_fails(monkeypatch) -> None:
    # Title is still usable even when the PID subcommand fails/returns
    # something unparseable — the three calls are independent.
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        _xdotool_side_effect("Some Window\n", 0, "not-a-number\n", 0, "some-class\n", 0),
    )

    assert LinuxAdapter().get_active_window() == ActiveWindow(
        title="Some Window", pid=None, wm_class="some-class"
    )


def test_get_active_window_wm_class_none_when_class_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        _xdotool_side_effect("Some Window\n", 0, "123\n", 0, "", 1),
    )

    assert LinuxAdapter().get_active_window() == ActiveWindow(title="Some Window", pid=123, wm_class=None)


def test_get_active_window_includes_bbox_when_geometry_available(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        _xdotool_side_effect(
            "PyCharm\n", 0, "123\n", 0, "jetbrains-pycharm\n", 0,
            geometry_stdout="WINDOW=12345\nX=10\nY=20\nWIDTH=800\nHEIGHT=600\n",
            geometry_rc=0,
        ),
    )

    result = LinuxAdapter().get_active_window()
    assert result is not None
    assert result.bbox == (10, 20, 800, 600)


def test_get_active_window_bbox_none_when_geometry_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/xdotool")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        _xdotool_side_effect("PyCharm\n", 0, "123\n", 0, "jetbrains-pycharm\n", 0),
    )

    result = LinuxAdapter().get_active_window()
    assert result is not None
    assert result.bbox is None


# --- brightness -----------------------------------------------------------


def test_brightness_backend_prefers_brightnessctl(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/brightnessctl" if name == "brightnessctl" else "/usr/bin/xrandr",
    )
    assert LinuxAdapter()._brightness_backend() == "brightnessctl"


def test_brightness_backend_falls_back_to_xrandr(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/xrandr" if name == "xrandr" else None,
    )
    assert LinuxAdapter()._brightness_backend() == "xrandr"


def test_brightness_backend_raises_without_any_tool(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError):
        LinuxAdapter()._brightness_backend()


def test_set_brightness_downgrades_to_xrandr_when_brightnessctl_lacks_permission(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/brightnessctl" if name == "brightnessctl" else "/usr/bin/xrandr",
    )
    calls: list[list[str]] = []

    def _run(args, **_kwargs):
        if args[:2] == ["brightnessctl", "set"]:
            raise subprocess.CalledProcessError(1, args, stderr="Permission denied")
        if args[:2] == ["xrandr", "--query"]:
            return MagicMock(returncode=0, stdout="eDP-1 connected primary 1920x1080+0+0\n")
        calls.append(args)
        return MagicMock(returncode=0)

    monkeypatch.setattr("core.os_adapter.linux.subprocess.run", _run)
    adapter = LinuxAdapter()

    adapter.set_brightness(40)

    assert calls == [["xrandr", "--output", "eDP-1", "--brightness", "0.40"]]
    # Sticky: subsequent reads/writes stay on xrandr, not back to brightnessctl.
    assert adapter._brightness_backend() == "xrandr"


def test_set_brightness_via_brightnessctl_clamps_to_safe_floor(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/brightnessctl")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0),
    )

    LinuxAdapter().set_brightness(0)

    assert calls == [["brightnessctl", "set", "5%"]]


def test_set_brightness_via_xrandr_uses_primary_output_and_fraction(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/xrandr" if name == "xrandr" else None,
    )
    calls: list[list[str]] = []

    def _run(args, **_kwargs):
        if args[:2] == ["xrandr", "--query"]:
            return MagicMock(
                returncode=0,
                stdout="Screen 0: minimum 320 x 200\neDP-1 connected primary 1920x1080+0+0\nHDMI-1 disconnected\n",
            )
        calls.append(args)
        return MagicMock(returncode=0)

    monkeypatch.setattr("core.os_adapter.linux.subprocess.run", _run)

    LinuxAdapter().set_brightness(50)

    assert calls == [["xrandr", "--output", "eDP-1", "--brightness", "0.50"]]


def test_get_brightness_parses_brightnessctl_machine_output(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/brightnessctl")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: MagicMock(returncode=0, stdout="amdgpu_bl1,backlight,127,67%,255\n"),
    )

    assert LinuxAdapter().get_brightness() == 67


def test_get_brightness_parses_xrandr_verbose_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/xrandr" if name == "xrandr" else None,
    )
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: MagicMock(returncode=0, stdout="\tGamma:      1.0:1.0:1.0\n\tBrightness: 0.75\n"),
    )

    assert LinuxAdapter().get_brightness() == 75


def test_lock_screen_prefers_loginctl(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0, stdout="", stderr=""),
    )

    LinuxAdapter().lock_screen()

    assert calls == [["loginctl", "lock-session"]]


def test_lock_screen_falls_back_to_xdg_screensaver(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "xdg-screensaver" else None,
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0, stdout="", stderr=""),
    )

    LinuxAdapter().lock_screen()

    assert calls == [["xdg-screensaver", "lock"]]


def test_lock_screen_tries_next_backend_when_one_fails(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []

    def _run(args, **_kwargs):
        calls.append(args)
        ok = args[0] != "loginctl"
        return MagicMock(returncode=0 if ok else 1, stdout="", stderr="no session")

    monkeypatch.setattr("core.os_adapter.linux.subprocess.run", _run)

    LinuxAdapter().lock_screen()

    assert calls == [["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"]]


def test_lock_screen_raises_without_any_backend(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError):
        LinuxAdapter().lock_screen()


def test_pause_media_pauses_only_playing_players(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/playerctl")
    calls: list[list[str]] = []

    def _run(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["playerctl", "--list-all"]:
            return MagicMock(returncode=0, stdout="firefox\nspotify\nvlc\n")
        if args[-1] == "status":
            player = args[2]
            playing = player in ("firefox", "spotify")
            return MagicMock(returncode=0, stdout="Playing\n" if playing else "Paused\n")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr("core.os_adapter.linux.subprocess.run", _run)

    paused = LinuxAdapter().pause_media()

    assert paused == ["firefox", "spotify"]
    assert ["playerctl", "--player", "firefox", "pause"] in calls
    assert ["playerctl", "--player", "spotify", "pause"] in calls
    assert ["playerctl", "--player", "vlc", "pause"] not in calls


def test_pause_media_returns_empty_without_playerctl(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    assert LinuxAdapter().pause_media() == []


def test_resume_media_plays_each_reported_player(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/playerctl")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0, stdout=""),
    )

    LinuxAdapter().resume_media(["firefox", "spotify"])

    assert calls == [
        ["playerctl", "--player", "firefox", "play"],
        ["playerctl", "--player", "spotify", "play"],
    ]


def test_resume_media_is_a_noop_for_empty_tokens(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/playerctl")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0),
    )

    LinuxAdapter().resume_media([])

    assert calls == []


def test_suspend_prefers_systemctl(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0),
    )

    LinuxAdapter().suspend()

    assert calls == [["systemctl", "suspend"]]


def test_suspend_falls_back_to_loginctl(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.os_adapter.linux.shutil.which",
        lambda name: "/usr/bin/loginctl" if name == "loginctl" else None,
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0),
    )

    LinuxAdapter().suspend()

    assert calls == [["loginctl", "suspend"]]


def test_suspend_raises_without_systemd(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError):
        LinuxAdapter().suspend()


def test_get_power_profile_reads_powerprofilesctl(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/powerprofilesctl")
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: MagicMock(returncode=0, stdout="performance\n"),
    )
    assert LinuxAdapter().get_power_profile() == "performance"


def test_set_power_profile_calls_powerprofilesctl(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/powerprofilesctl")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "core.os_adapter.linux.subprocess.run",
        lambda args, **k: calls.append(args) or MagicMock(returncode=0),
    )

    LinuxAdapter().set_power_profile("power-saver")

    assert calls == [["/usr/bin/powerprofilesctl", "set", "power-saver"]]


def test_set_power_profile_rejects_unknown_value(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: "/usr/bin/powerprofilesctl")
    with pytest.raises(RuntimeError):
        LinuxAdapter().set_power_profile("ludicrous")


def test_power_profile_raises_without_the_daemon(monkeypatch) -> None:
    monkeypatch.setattr("core.os_adapter.linux.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError):
        LinuxAdapter().get_power_profile()
