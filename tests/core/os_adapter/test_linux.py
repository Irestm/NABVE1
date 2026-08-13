from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

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
