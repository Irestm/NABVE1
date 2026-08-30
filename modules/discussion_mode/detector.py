from __future__ import annotations

import re

from core.voice.phrase_matching import fuzzy_contains_phrase
from modules.discussion_mode.config import DEFAULT_ENTER_PHRASES, DEFAULT_EXIT_PHRASES

# No listening thread here — enter phrases are matched by core/voice/intent.py
# in the normal command pass; exit / "what do you think" phrases are matched
# on the already-transcribed line inside pipeline.py's discussion sub-loop.


def enter_phrases(custom_phrase: str | None) -> tuple[str, ...]:
    if not custom_phrase:
        return DEFAULT_ENTER_PHRASES
    return (*DEFAULT_ENTER_PHRASES, custom_phrase)


def exit_phrases(custom_phrase: str | None) -> tuple[str, ...]:
    if not custom_phrase:
        return DEFAULT_EXIT_PHRASES
    return (*DEFAULT_EXIT_PHRASES, custom_phrase)


def is_exit_phrase(text: str, custom_phrase: str | None = None) -> bool:
    return any(fuzzy_contains_phrase(text, phrase) for phrase in exit_phrases(custom_phrase))


_OPINION_LEAD = re.compile(
    r"\b(?:что\s+(?:ты\s+)?думаешь|как\s+(?:ты\s+)?считаешь|тво[её]\s+мнение|"
    r"а\s+ты\s+что\s+скажешь|что\s+скажешь)\b",
    re.IGNORECASE,
)


def is_opinion_request(text: str, assistant_name: str | None) -> bool:
    """True when the line is the code phrase asking Jarvis to weigh in —
    "Что думаешь, <имя ассистента>". The lead-in ("что думаешь" / "твоё
    мнение" / ...) is required; the assistant's own name is required too
    when one is configured, so an ordinary "а ты что думаешь" between the
    two humans doesn't pull the assistant into the conversation."""
    if not text or not _OPINION_LEAD.search(text):
        return False
    if assistant_name:
        return fuzzy_contains_phrase(text, assistant_name.lower())
    return True
