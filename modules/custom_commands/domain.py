from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ActionType(str, Enum):
    OPEN_LINK = "open_link"
    PLAY_AUDIO = "play_audio"
    OPEN_MEDIA = "open_media"
    LAUNCH_APP = "launch_app"
    # Not executed by this module at all — see
    # modules/custom_commands/dispatcher.py's module docstring and
    # core/voice/pipeline.py's custom-command handling: matching this type
    # substitutes the stored instruction text back into the normal
    # interpret()/plugin/system-command/ai_bridge chain, so it behaves as a
    # personal shortcut for a longer spoken request rather than a direct
    # action.
    TEXT_INSTRUCTION = "text_instruction"


# action_type -> the payload keys considered risky enough to log in full on
# create/update (see service_layer.create_command/update_command) — see the
# ТЗ's "логировать создание/редактирование launch_app и text_instruction".
LOGGED_ACTION_TYPES = (ActionType.LAUNCH_APP, ActionType.TEXT_INSTRUCTION)


@dataclass
class CustomCommand:
    id: str
    trigger_phrase: str
    action_type: ActionType
    action_payload: dict = field(default_factory=dict)
    created_at: datetime | None = None
