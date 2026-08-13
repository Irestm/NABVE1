from __future__ import annotations

import asyncio
import threading
import time

import psutil

from core.config import BASE_DIR
from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.hardware_adaptive.events import HardwareAlertRaised

logger = get_logger(__name__)

_BATTERY_LOW_PERCENT = 15
_DISK_LOW_FREE_PERCENT = 10
# Once a metric has alerted, it won't alert again for this long even if the
# threshold is still crossed on every poll — a laptop sitting at 8% battery
# for an hour should be mentioned once, not every _interval_seconds.
_ALERT_COOLDOWN_SECONDS = 30 * 60


class HardwareMonitor:
    """Background poller: every `interval_seconds`, checks a few local,
    zero-cost system metrics via psutil (no network, no paid service) and
    publishes HardwareAlertRaised when a threshold is crossed, gated by a
    per-metric cooldown. Mirrors modules.calendar.notifier.ReminderChecker's
    shape — this class only owns thread/scheduling/threshold logic; actual
    delivery is a message-bus subscriber (see
    core.voice.proactive_announcer.ProactiveAnnouncer)."""

    def __init__(self, interval_seconds: int = 60, bus: MessageBus = message_bus) -> None:
        self._interval_seconds = interval_seconds
        self._bus = bus
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_alert_at: dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hardware-monitor")
        self._thread.start()
        logger.info("Hardware monitor started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Hardware monitor stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._check_once()
            self._stop_event.wait(self._interval_seconds)

    def _check_once(self) -> None:
        try:
            asyncio.run(self._check_once_async())
        except Exception:
            logger.exception("Failed while checking hardware metrics")

    async def _check_once_async(self) -> None:
        await self._check_battery()
        await self._check_disk()

    def _should_alert(self, metric: str) -> bool:
        last = self._last_alert_at.get(metric)
        return last is None or (time.monotonic() - last) >= _ALERT_COOLDOWN_SECONDS

    async def _publish(self, metric: str, severity: str, message: str, value: float) -> None:
        self._last_alert_at[metric] = time.monotonic()
        await self._bus.publish(HardwareAlertRaised(metric=metric, severity=severity, message=message, value=value))

    async def _check_battery(self) -> None:
        # None on desktops/most Linux setups without a battery sensor — not
        # an error, just nothing to check.
        battery = psutil.sensors_battery()
        if battery is None or battery.power_plugged:
            return
        if battery.percent >= _BATTERY_LOW_PERCENT or not self._should_alert("battery"):
            return
        await self._publish(
            "battery",
            "warning",
            f"Батарея разряжена: осталось {round(battery.percent)} процентов",
            battery.percent,
        )

    async def _check_disk(self) -> None:
        usage = psutil.disk_usage(str(BASE_DIR))
        free_percent = 100 - usage.percent
        if free_percent >= _DISK_LOW_FREE_PERCENT or not self._should_alert("disk"):
            return
        await self._publish(
            "disk",
            "warning",
            f"Заканчивается место на диске: свободно {round(free_percent)} процентов",
            free_percent,
        )
