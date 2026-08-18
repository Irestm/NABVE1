from __future__ import annotations

from dataclasses import dataclass

from core.message_bus import Event


@dataclass(frozen=True)
class TimerFired(Event):
    """Published when a countdown timer (see service_layer.start_timer)
    reaches zero — subscribers decide how to actually notify. `message` is
    pre-built (not just `label`) specifically so this can subscribe
    directly to core.voice.proactive_announcer.ProactiveAnnouncer.handle,
    the same "unprompted spoken notification" consumer
    modules.hardware_adaptive.events.HardwareAlertRaised already uses,
    without needing a dedicated announcer class of its own."""

    timer_id: int
    label: str
    message: str
