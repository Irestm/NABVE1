from __future__ import annotations

import subprocess

import pytest

from modules.gesture_control import cursor_zoom as cz


@pytest.fixture(autouse=True)
def _isolate_recovery_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cz, "_RECOVERY_FILE", tmp_path / "cursor_size.recovery")


class _FakeRun:
    """A faithful-enough gsettings: `set` mutates state that `get` reads
    back, so cursor_zoom's read-back verification is exercised. `fail_sets`
    upcoming `set` calls are dropped (still recorded in `sets`): a no-op
    that reports success, or a raise when `raise_sets` is on."""

    def __init__(self, initial: int = 24) -> None:
        self.value = initial
        self.sets: list[int] = []
        self.fail_sets = 0
        self.raise_sets = False

    def __call__(self, cmd, **_kwargs):
        if "get" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"uint32 {self.value}\n", stderr="")
        if "set" in cmd:
            requested = int(cmd[-1])
            self.sets.append(requested)
            if self.fail_sets > 0:
                self.fail_sets -= 1
                if self.raise_sets:
                    raise subprocess.TimeoutExpired(cmd, cz._SET_TIMEOUT_S)
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            self.value = requested
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(cmd)


@pytest.fixture
def gnome(monkeypatch):
    fake = _FakeRun()
    monkeypatch.setattr(cz, "sys", type("S", (), {"platform": "linux"}))
    monkeypatch.setattr(cz.shutil, "which", lambda _name: "/usr/bin/gsettings")
    monkeypatch.setattr(cz.subprocess, "run", fake)
    monkeypatch.setattr(cz.time, "sleep", lambda _s: None)  # no real backoff waits
    return fake


def test_enlarge_then_restore_roundtrips_the_cursor_size(gnome) -> None:
    zoom = cz.CursorZoom()
    zoom.enlarge()
    assert gnome.sets == [round(24 * cz.CURSOR_SCALE)]
    assert gnome.value == round(24 * cz.CURSOR_SCALE)
    zoom.restore()
    assert gnome.sets == [round(24 * cz.CURSOR_SCALE), 24]
    assert gnome.value == 24


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
    assert gnome.value == 20
    assert not cz._RECOVERY_FILE.exists()  # and the marker cleared


def test_enlarge_heals_a_prior_unclean_exit_first(gnome) -> None:
    cz._RECOVERY_FILE.write_text("20")  # left over from a killed run
    zoom = cz.CursorZoom()
    zoom.enlarge()
    # first the recovery put 20 back, then the fresh enlarge scaled from 20
    assert gnome.sets == [20, round(20 * cz.CURSOR_SCALE)]
    assert cz._RECOVERY_FILE.read_text() == "20"  # a fresh marker holds the 20 base


def test_recover_if_stale_no_file_is_a_noop(gnome) -> None:
    cz.CursorZoom().recover_if_stale()
    assert gnome.sets == []


# --- hardening: a write that times out / no-ops must not be lost ---


def test_restore_keeps_marker_and_original_when_the_write_fails(gnome) -> None:
    zoom = cz.CursorZoom()
    zoom.enlarge()
    assert zoom._original == 24 and cz._RECOVERY_FILE.read_text() == "24"

    gnome.fail_sets = cz._SET_ATTEMPTS  # every retry inside restore() no-ops
    gnome.raise_sets = True
    zoom.restore()
    assert zoom._original == 24  # NOT dropped
    assert cz._RECOVERY_FILE.read_text() == "24"  # marker kept for the next try
    assert gnome.value == round(24 * cz.CURSOR_SCALE)  # still enlarged

    gnome.fail_sets = 0
    gnome.raise_sets = False
    zoom.restore()  # the retry succeeds
    assert zoom._original is None
    assert gnome.value == 24
    assert not cz._RECOVERY_FILE.exists()


def test_a_write_that_does_not_stick_is_not_reported_as_success(gnome) -> None:
    gnome.fail_sets = cz._SET_ATTEMPTS  # `set` returns 0 but the value never moves
    zoom = cz.CursorZoom()
    zoom.enlarge()
    assert zoom._original is None  # enlarge did not latch a bogus original
    assert gnome.sets == [round(24 * cz.CURSOR_SCALE)] * cz._SET_ATTEMPTS  # it retried
    assert not cz._RECOVERY_FILE.exists()  # and cleaned up its own marker


def test_recover_if_stale_keeps_the_marker_when_it_cannot_write(gnome) -> None:
    cz._RECOVERY_FILE.write_text("20")
    gnome.fail_sets = cz._SET_ATTEMPTS
    gnome.raise_sets = True
    cz.CursorZoom().recover_if_stale()
    assert cz._RECOVERY_FILE.read_text() == "20"  # not cleared on failure

    gnome.fail_sets = 0
    gnome.raise_sets = False
    cz.CursorZoom().recover_if_stale()
    assert gnome.value == 20
    assert not cz._RECOVERY_FILE.exists()


def test_enlarge_after_a_failed_recovery_uses_the_marker_value_not_the_inflated_size(gnome) -> None:
    # A previous session enlarged 24 -> 36 and then failed to restore, so
    # the marker still says 24 while the live size is stuck at 36.
    cz._RECOVERY_FILE.write_text("24")
    gnome.value = round(24 * cz.CURSOR_SCALE)  # 36, stuck
    gnome.fail_sets = cz._SET_ATTEMPTS  # recovery inside enlarge() also fails
    gnome.raise_sets = True

    zoom = cz.CursorZoom()
    zoom.enlarge()

    # enlarge fell back to the marker's 24 as the base, not the stuck 36
    assert zoom._original == 24
    assert cz._RECOVERY_FILE.read_text() == "24"  # marker preserved, not overwritten with 36
    # after the failed recovery, gnome.fail_sets is exhausted, so the actual
    # enlarge write lands: 24 * scale, not 36 * scale
    assert gnome.value == round(24 * cz.CURSOR_SCALE)

    zoom.restore()
    assert gnome.value == 24
    assert not cz._RECOVERY_FILE.exists()
