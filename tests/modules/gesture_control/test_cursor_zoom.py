from __future__ import annotations

import subprocess

import pytest

from modules.gesture_control import cursor_zoom as cz


@pytest.fixture(autouse=True)
def _isolate_recovery_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cz, "_RECOVERY_FILE", tmp_path / "cursor_size.recovery")


class _FakeRun:
    def __init__(self, get_value: str) -> None:
        self.get_value = get_value
        self.sets: list[int] = []

    def __call__(self, cmd, **_kwargs):
        if "get" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.get_value, stderr="")
        if "set" in cmd:
            self.sets.append(int(cmd[-1]))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(cmd)


@pytest.fixture
def gnome(monkeypatch):
    fake = _FakeRun("uint32 24\n")
    monkeypatch.setattr(cz, "sys", type("S", (), {"platform": "linux"}))
    monkeypatch.setattr(cz.shutil, "which", lambda _name: "/usr/bin/gsettings")
    monkeypatch.setattr(cz.subprocess, "run", fake)
    return fake


def test_enlarge_then_restore_roundtrips_the_cursor_size(gnome) -> None:
    zoom = cz.CursorZoom()
    zoom.enlarge()
    assert gnome.sets == [round(24 * cz.CURSOR_SCALE)]
    zoom.restore()
    assert gnome.sets == [round(24 * cz.CURSOR_SCALE), 24]


def test_enlarge_is_idempotent(gnome) -> None:
    zoom = cz.CursorZoom()
    zoom.enlarge()
    zoom.enlarge()
    assert len(gnome.sets) == 1


def test_restore_without_enlarge_is_a_noop(gnome) -> None:
    zoom = cz.CursorZoom()
    zoom.restore()
    assert gnome.sets == []


def test_no_gsettings_is_a_silent_noop(monkeypatch) -> None:
    monkeypatch.setattr(cz.shutil, "which", lambda _name: None)
    zoom = cz.CursorZoom()
    zoom.enlarge()
    zoom.restore()  # must not raise


def test_non_linux_is_a_silent_noop(monkeypatch) -> None:
    monkeypatch.setattr(cz, "sys", type("S", (), {"platform": "win32"}))
    called = False

    def _boom(*_a, **_k):
        nonlocal called
        called = True

    monkeypatch.setattr(cz.subprocess, "run", _boom)
    zoom = cz.CursorZoom()
    zoom.enlarge()
    assert called is False


def test_recover_if_stale_restores_size_from_the_recovery_file(gnome) -> None:
    # live size (fake) is 24; the recovery marker says it should be 20
    cz._RECOVERY_FILE.write_text("20")
    cz.CursorZoom().recover_if_stale()
    assert gnome.sets == [20]  # size put back
    assert not cz._RECOVERY_FILE.exists()  # and the marker cleared


def test_enlarge_heals_a_prior_unclean_exit_first(gnome) -> None:
    cz._RECOVERY_FILE.write_text("20")  # left over from a killed run
    zoom = cz.CursorZoom()
    zoom.enlarge()
    # first the recovery put 20 back, then the fresh enlarge scaled 24 -> 36
    assert gnome.sets == [20, round(24 * cz.CURSOR_SCALE)]


def test_recover_if_stale_no_file_is_a_noop(gnome) -> None:
    cz.CursorZoom().recover_if_stale()
    assert gnome.sets == []
