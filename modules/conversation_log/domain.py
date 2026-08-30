from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["user", "assistant"]
Source = Literal["voice", "text"]


@dataclass(frozen=True)
class ConversationTurn:
    # ISO-8601 UTC, second precision - the frontend formats the local
    # HH:MM / day separators itself, so storing a single unambiguous
    # instant (not a pre-formatted local string) is enough here.
    timestamp: str
    role: Role
    text: str
    # "voice" for a spoken exchange through the wake-word loop,
    # "text" for one typed into the desktop UI's text chat - kept so the
    # merged on-screen log can still tell the two apart if it ever needs to.
    source: Source

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "role": self.role,
            "text": self.text,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ConversationTurn:
        return cls(
            timestamp=str(raw["timestamp"]),
            role=raw["role"],
            text=str(raw["text"]),
            source=raw["source"],
        )
