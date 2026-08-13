from __future__ import annotations

from types import SimpleNamespace

from core.message_bus import MessageBus
from modules.hardware_adaptive.events import HardwareAlertRaised
from modules.hardware_adaptive.system_monitor import HardwareMonitor


def _monitor() -> tuple[HardwareMonitor, list[HardwareAlertRaised]]:
    bus = MessageBus()
    received: list[HardwareAlertRaised] = []

    async def _record(event: HardwareAlertRaised) -> None:
        received.append(event)

    bus.subscribe(HardwareAlertRaised, _record)
    return HardwareMonitor(bus=bus), received


async def test_low_unplugged_battery_publishes_alert(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery",
        lambda: SimpleNamespace(percent=10, power_plugged=False),
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=50),
    )

    await monitor._check_once_async()

    assert [e.metric for e in received] == ["battery"]


async def test_low_but_plugged_in_battery_does_not_alert(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery",
        lambda: SimpleNamespace(percent=5, power_plugged=True),
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=50),
    )

    await monitor._check_once_async()

    assert received == []


async def test_no_battery_sensor_does_not_crash(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery", lambda: None
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=50),
    )

    await monitor._check_once_async()

    assert received == []


async def test_low_free_disk_space_publishes_alert(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery",
        lambda: SimpleNamespace(percent=100, power_plugged=True),
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=95),  # only 5% free
    )

    await monitor._check_once_async()

    assert [e.metric for e in received] == ["disk"]


async def test_alert_does_not_repeat_within_cooldown(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery",
        lambda: SimpleNamespace(percent=10, power_plugged=False),
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=50),
    )

    await monitor._check_once_async()
    await monitor._check_once_async()

    assert len(received) == 1


async def test_alert_fires_again_after_cooldown_elapses(monkeypatch) -> None:
    monitor, received = _monitor()
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.sensors_battery",
        lambda: SimpleNamespace(percent=10, power_plugged=False),
    )
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.psutil.disk_usage",
        lambda path: SimpleNamespace(percent=50),
    )

    fake_time = [1000.0]
    monkeypatch.setattr(
        "modules.hardware_adaptive.system_monitor.time.monotonic", lambda: fake_time[0]
    )

    await monitor._check_once_async()
    fake_time[0] += 31 * 60
    await monitor._check_once_async()

    assert len(received) == 2
