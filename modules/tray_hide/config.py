from __future__ import annotations

# Custom phrases are stored as ordinary profile facts (see
# modules/user_profile/domain.py's STOP_WORD_KEY for the same pattern),
# through the existing generic profile_set/profile_get commands — no
# dedicated storage or API for this module needed.
HIDE_PHRASE_KEY = "tray_hide_phrase"
SHOW_PHRASE_KEY = "tray_show_phrase"

DEFAULT_HIDE_PHRASES: tuple[str, ...] = (
    "спрячься",
    "скройся",
    "уйди в трей",
    "спрячься в трей",
)
DEFAULT_SHOW_PHRASES: tuple[str, ...] = (
    "покажись",
    "вернись",
    "выйди",
    "покажи окно",
)
