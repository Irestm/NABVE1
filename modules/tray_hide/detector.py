from __future__ import annotations

from modules.tray_hide.config import DEFAULT_HIDE_PHRASES, DEFAULT_SHOW_PHRASES

# No separate listening thread/detector class here on purpose: hide/show
# phrases are checked in the same background STT pass that already listens
# for the wake word and the stop word (see core/voice/wake_word.py's
# listen_for_phrases and core/voice/pipeline.py's _wait_for_wake_or_pause),
# so this module only supplies the phrase-variant lists that pass expects.


def hide_phrases(custom_phrase: str | None) -> tuple[str, ...]:
    if not custom_phrase:
        return DEFAULT_HIDE_PHRASES
    return (*DEFAULT_HIDE_PHRASES, custom_phrase)


def show_phrases(custom_phrase: str | None) -> tuple[str, ...]:
    if not custom_phrase:
        return DEFAULT_SHOW_PHRASES
    return (*DEFAULT_SHOW_PHRASES, custom_phrase)
