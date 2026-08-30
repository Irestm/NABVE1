from __future__ import annotations

from dataclasses import dataclass

from core.message_bus import Event


@dataclass(frozen=True)
class GestureAnnouncement(Event):
    """Spoken feedback from the gesture worker (calibration prompts, "режим
    жестов включён", errors). Carries a ready message so
    core/voice/proactive_announcer.ProactiveAnnouncer speaks it directly —
    same shape as modules/software_installer's SoftwareInstallFinished."""

    message: str
