from __future__ import annotations

import random

from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import CONFIRMATION_PHRASE_ENABLED_KEY, DEFAULT_GENDER, GENDER_KEY
from modules.user_profile.uow import ProfileUnitOfWork

# Jarvis-style "acknowledge, then act" phrasing — see core/voice/pipeline.py's
# _handle_command, the only caller of get_confirmation_phrase(). Several
# variants per gender so a command-heavy session doesn't hear the exact same
# phrase back to back (see _last_phrase below).
_MALE_PHRASES = ("Да, сэр", "Слушаюсь, сэр", "Выполняю, сэр")
_FEMALE_PHRASES = ("Да, мэм", "Слушаюсь, мэм", "Выполняю, мэм")

# The voice loop runs on a single dedicated thread (core/voice/pipeline.py's
# VoiceAssistantLoop), so plain module state is enough to avoid immediate
# repeats without needing a lock or per-session object.
_last_phrase: str | None = None


def is_enabled() -> bool:
    return profile_service_layer.get_fact(ProfileUnitOfWork(), CONFIRMATION_PHRASE_ENABLED_KEY) == "1"


def get_confirmation_phrase() -> str:
    """Picks a gendered acknowledgement phrase, read fresh from the profile
    every call (like STOP_WORD_KEY etc. in pipeline.py) so a gender change in
    settings takes effect on the very next command. Avoids repeating the
    same phrase twice in a row when more than one variant is available."""
    global _last_phrase
    gender = profile_service_layer.get_fact(ProfileUnitOfWork(), GENDER_KEY) or DEFAULT_GENDER
    phrases = _FEMALE_PHRASES if gender == "female" else _MALE_PHRASES
    candidates = [phrase for phrase in phrases if phrase != _last_phrase] or list(phrases)
    phrase = random.choice(candidates)
    _last_phrase = phrase
    return phrase
