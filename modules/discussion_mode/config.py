from __future__ import annotations

# Custom enter/exit phrases are stored as ordinary profile facts (same
# pattern as modules/tray_hide/config.py's HIDE_PHRASE_KEY), set through the
# generic profile_set/profile_get commands — no dedicated storage needed.
DISCUSSION_ENTER_PHRASE_KEY = "discussion_enter_phrase"
DISCUSSION_EXIT_PHRASE_KEY = "discussion_exit_phrase"

DEFAULT_ENTER_PHRASES: tuple[str, ...] = (
    "давай подискутируем",
    "давай подискутируем втроём",
    "режим дискуссии",
    "включи режим дискуссии",
    "давай обсудим втроём",
)

DEFAULT_EXIT_PHRASES: tuple[str, ...] = (
    "выйди из режима дискуссии",
    "выйти из режима дискуссии",
    "хватит слушать",
    "прекрати дискуссию",
    "закончи дискуссию",
)

# Median-f0 gap (Hz) above which a new utterance is treated as a second
# speaker rather than the same person. Deliberately generous — this is a
# "probably two different voices" heuristic, not real diarization.
SPEAKER_PITCH_GAP_HZ = 35.0
