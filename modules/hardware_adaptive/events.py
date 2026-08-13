from __future__ import annotations

from dataclasses import dataclass

from core.message_bus import Event


@dataclass(frozen=True)
class HardwareAlertRaised(Event):
    """Published when a local system metric (battery, disk space — see
    modules/hardware_adaptive/system_monitor.py) crosses a low threshold.
    Consumed by core.voice.proactive_announcer.ProactiveAnnouncer to speak
    it aloud, gated on the voice loop actually running and not mid-turn."""

    metric: str
    severity: str
    message: str
    value: float
