from __future__ import annotations

import asyncio
import threading
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

    def set_min_cutoff(self, _value: float) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self) -> None:
        self.screen_size = (1920, 1080)
        self.released = False

    def click_up(self) -> None:
        pass

    def current_pos(self) -> tuple[int, int]:
        return (0, 0)

    def physical_mouse_moved(self, _threshold_px: int) -> bool:
        return False

    def sync_last_set(self) -> None:
        pass

    def move_cursor(self, _x: int, _y: int) -> None:
        pass

    def last_pos(self) -> tuple[int, int] | None:
        return None

    def trigger_zoom(self, _direction: str) -> None:
        pass

    def trigger_window_switch(self, _direction: str) -> None:
        pass

    def click_down(self) -> None:
        pass

    def release(self) -> None:
        self.released = True


@pytest.fixture(autouse=True)
def _no_profile_db(monkeypatch):
    monkeypatch.setattr(gd.calibration, "load_min_cutoff", lambda: 1.2)
    monkeypatch.setattr(gd.calibration, "load_deadzone_px", lambda: 4)
    monkeypatch.setattr(gd.calibration, "load_click_gap_thresholds", lambda: (0.22, 0.40))
    monkeypatch.setattr(gd.calibration, "load_zone_bounds", lambda: None)
    monkeypatch.setattr(gd.calibration.profile_service_layer, "set_fact", lambda *a, **k: None)
    # Never touch the real desktop cursor size from a test run.
    monkeypatch.setattr(gd.cursor_zoom, "enlarge", lambda: None)
    monkeypatch.setattr(gd.cursor_zoom, "restore", lambda: None)


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


def test_stop_that_times_out_keeps_handle_and_blocks_restart(monkeypatch) -> None:
    monkeypatch.setattr(gd, "_STOP_JOIN_TIMEOUT_S", 0.2)
    release = threading.Event()

    class _SlowCloseTracker(_FakeTracker):
        def close(self) -> None:  # blocks the worker's cleanup past the join
            release.wait(3.0)
            super().close()

    monkeypatch.setattr(gd, "HandTracker", _SlowCloseTracker)
    monkeypatch.setattr(gd, "CursorController", _FakeCursor)
    controller = gd.GestureController(bus=MessageBus())

    controller.start()
    _wait_active(controller, True)
    try:
        assert controller.stop() is False  # join timed out
        assert controller._thread is not None  # handle NOT cleared
        assert controller.start() is False  # no second worker over the hung one
        assert "остановить" in (controller.last_error() or "").lower()
    finally:
        release.set()
        _wait_active(controller, False, timeout=5.0)


def test_camera_unavailable_is_surfaced_and_shuts_down(monkeypatch) -> None:
    class _FatalTracker(_FakeTracker):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self._n = 0

        def read(self):
            self._n += 1
            if self._n >= 2:
                raise gd.CameraUnavailable("камера не отдаёт кадры")
            return None

    monkeypatch.setattr(gd, "HandTracker", _FatalTracker)
    monkeypatch.setattr(gd, "CursorController", _FakeCursor)
    controller = gd.GestureController(bus=MessageBus())

    controller.start()
    _wait_active(controller, False)
    assert "не отдаёт кадры" in (controller.last_error() or "")
    assert gd.overlay_state.active is False


def test_overlay_inactive_until_first_frame(monkeypatch) -> None:
    controller, _ = _make_controller(monkeypatch)  # _FakeTracker.read() -> None forever
    controller.start()
    _wait_active(controller, True)
    try:
        assert gd.overlay_state.active is False  # worker alive but no frames yet
    finally:
        controller.stop()


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

    def cancel_calibration(self) -> bool:
        self.calls.append("cancel_cal")
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


def test_gesture_calibrate_cancel_handler(monkeypatch) -> None:
    fake = _FakeController()
    monkeypatch.setattr(gd, "gesture_controller", fake)
    r_off = asyncio.run(gd._handle_gesture_calibrate_cancel({}))
    assert "не запущена" in r_off["message"]
    fake._active = True
    r_on = asyncio.run(gd._handle_gesture_calibrate_cancel({}))
    assert "тмен" in r_on["message"] and "cancel_cal" in fake.calls


def test_announce_is_non_blocking_and_delivered_via_the_bound_loop() -> None:
    delivered: list[str] = []

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        bus = MessageBus()

        async def _handler(evt) -> None:
            delivered.append(evt.message)

        bus.subscribe(gd.GestureAnnouncement, _handler)
        ctrl = gd.GestureController(bus=bus)
        ctrl.bind_loop(loop)

        t0 = time.monotonic()
        ctrl._announce("проверка связи")
        assert time.monotonic() - t0 < 0.2  # returned at once, no TTS wait

        deadline = time.monotonic() + 3.0
        while not delivered and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert delivered == ["проверка связи"]

    asyncio.run(_main())


def test_commands_register() -> None:
    dispatcher = CommandDispatcher()
    gd.register_commands(dispatcher)
    names = {c.name for c in dispatcher.list_commands()}
    assert {
        "gesture_start", "gesture_stop", "gesture_calibrate", "gesture_calibrate_cancel"
    } <= names
