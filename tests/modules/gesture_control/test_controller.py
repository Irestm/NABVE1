from __future__ import annotations

import asyncio
import time

import pytest

import modules.gesture_control.dispatcher as gd
from core.dispatcher import CommandDispatcher
from core.message_bus import MessageBus


class _FakeTracker:
    def __init__(self, *_a, **_k) -> None:
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self):
        return None  # no frames -> worker just idles until stopped

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self) -> None:
        self.screen_size = (1920, 1080)
        self.released = False

    def click_up(self) -> None:
        pass

    def release(self) -> None:
        self.released = True


@pytest.fixture(autouse=True)
def _no_profile_db(monkeypatch):
    monkeypatch.setattr(gd.profile_service_layer, "get_fact", lambda uow, key: None)
    monkeypatch.setattr(gd.profile_service_layer, "set_fact", lambda *a, **k: None)
    monkeypatch.setattr(gd.calibration, "load_threshold", lambda: 0.05)
    monkeypatch.setattr(gd.calibration.profile_service_layer, "set_fact", lambda *a, **k: None)


def _make_controller(monkeypatch) -> tuple[gd.GestureController, _FakeTracker]:
    holder: dict[str, _FakeTracker] = {}

    def _tracker_factory(*a, **k):
        holder["t"] = _FakeTracker()
        return holder["t"]

    monkeypatch.setattr(gd, "HandTracker", _tracker_factory)
    monkeypatch.setattr(gd, "CursorController", _FakeCursor)
    controller = gd.GestureController(bus=MessageBus())
    return controller, holder  # type: ignore[return-value]


def _wait_active(controller: gd.GestureController, want: bool, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.is_active() == want:
            return
        time.sleep(0.02)
    raise AssertionError(f"controller.is_active() never became {want}")


def test_start_then_stop_toggles_and_releases_camera(monkeypatch) -> None:
    controller, holder = _make_controller(monkeypatch)

    assert controller.start() is True
    _wait_active(controller, True)
    assert controller.start() is False  # already running

    assert controller.stop() is True
    _wait_active(controller, False)
    assert controller.stop() is False  # already stopped
    assert holder["t"].closed is True


def test_worker_failure_to_open_camera_is_surfaced(monkeypatch) -> None:
    def _boom(*_a, **_k):
        class _T:
            def open(self):
                raise RuntimeError("camera busy")

        return _T()

    monkeypatch.setattr(gd, "HandTracker", _boom)
    monkeypatch.setattr(gd, "CursorController", _FakeCursor)
    controller = gd.GestureController(bus=MessageBus())

    controller.start()
    _wait_active(controller, False)
    assert "camera busy" in (controller.last_error() or "")


def test_recalibration_needs_an_active_session(monkeypatch) -> None:
    controller, _ = _make_controller(monkeypatch)
    assert controller.request_recalibration() is False
    controller.start()
    _wait_active(controller, True)
    assert controller.request_recalibration() is True
    controller.stop()


# --- command handlers ---


class _FakeController:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._active = False

    def start(self) -> bool:
        self.calls.append("start")
        was = self._active
        self._active = True
        return not was

    def stop(self) -> bool:
        self.calls.append("stop")
        was = self._active
        self._active = False
        return was

    def request_recalibration(self) -> bool:
        self.calls.append("recal")
        return self._active


def test_gesture_command_handlers(monkeypatch) -> None:
    fake = _FakeController()
    monkeypatch.setattr(gd, "gesture_controller", fake)

    r1 = asyncio.run(gd._handle_gesture_start({}))
    assert fake.calls == ["start"] and r1["active"] is True

    r2 = asyncio.run(gd._handle_gesture_start({}))
    assert "уже включён" in r2["message"]

    r3 = asyncio.run(gd._handle_gesture_stop({}))
    assert r3["active"] is False

    fake._active = True
    r4 = asyncio.run(gd._handle_gesture_calibrate({}))
    assert "калибр" in r4["message"].lower()


def test_gesture_calibrate_fails_when_inactive(monkeypatch) -> None:
    monkeypatch.setattr(gd, "gesture_controller", _FakeController())
    with pytest.raises(RuntimeError):
        asyncio.run(gd._handle_gesture_calibrate({}))


def test_commands_register() -> None:
    dispatcher = CommandDispatcher()
    gd.register_commands(dispatcher)
    names = {c.name for c in dispatcher.list_commands()}
    assert {"gesture_start", "gesture_stop", "gesture_calibrate"} <= names
