from __future__ import annotations

from core.config import SYSTEM_PROMPT_PREFIX
from modules.user_profile import service_layer
from modules.user_profile.communication_styles import get_current_style
from modules.user_profile.domain import ASSISTANT_NAME_KEY
from modules.user_profile.uow import ProfileUnitOfWork

__all__ = ["SYSTEM_PROMPT_PREFIX", "apply_system_prompt"]


def apply_system_prompt(text: str) -> str:
    """Prefixes `text` with the assistant's provider-independent style
    instruction, so Gemini/ChatGPT/DeepSeek/Grok and the local adaptive model
    all answer in the same tone. Call this at the single choke point where a
    prompt is about to be sent to a model — not at every call site — so the
    tone stays consistent by construction.

    The base instruction (numbers as words, no filler) is always applied;
    on top of it, the communication style chosen during onboarding (see
    modules.user_profile.onboarding._ask_communication_style) adds a
    personality-specific fragment, and the assistant's own chosen name (if
    any) is mentioned so the model answers consistently if asked for it.
    Before onboarding runs, both are simply absent — same behavior as
    before this feature existed."""
    style = get_current_style()
    prefix = f"{SYSTEM_PROMPT_PREFIX} {style.prompt_fragment}"

    assistant_name = service_layer.get_fact(ProfileUnitOfWork(), ASSISTANT_NAME_KEY)
    if assistant_name:
        prefix = f"{prefix} Тебя зовут {assistant_name}."

    return f"{prefix}\n\n{text}"
