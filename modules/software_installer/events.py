from __future__ import annotations

from dataclasses import dataclass

from core.message_bus import Event


@dataclass(frozen=True)
class SoftwareInstallFinished(Event):
    """Published by modules/software_installer/installer.py when a
    background install ends (success or failure). Carries a pre-built
    Russian `message` so core/voice/proactive_announcer.ProactiveAnnouncer
    can speak it directly, the same shape modules/timer's TimerFired uses."""

    app: str
    success: bool
    message: str
