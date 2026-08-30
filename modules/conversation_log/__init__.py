from __future__ import annotations

from modules.conversation_log.domain import ConversationTurn, Role, Source
from modules.conversation_log.store import ConversationLog

# Process-wide singleton - the voice loop and the API handlers both record
# through this same instance so the on-screen log is one merged stream.
conversation_log = ConversationLog()


def record_user(text: str, source: Source) -> None:
    if text and text.strip():
        conversation_log.append("user", text, source)


def record_assistant(text: str, source: Source) -> None:
    if text and text.strip():
        conversation_log.append("assistant", text, source)


__all__ = [
    "ConversationLog",
    "ConversationTurn",
    "Role",
    "Source",
    "conversation_log",
    "record_assistant",
    "record_user",
]
