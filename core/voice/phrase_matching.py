from __future__ import annotations

import re
from difflib import SequenceMatcher

# Shared by core/voice/wake_word.py (wake word + stop word) and
# core/voice/intent.py (yes/no confirmation, shutdown/restart triggers) —
# three independent "does this short phrase appear in what was said"
# problems that all had the same sliding-window fuzzy-match logic
# duplicated across files before this was pulled out.
PHRASE_SIMILARITY_THRESHOLD = 0.75


def _fold_yo(word: str) -> str:
    """Folds ё -> е before comparing. Russian is routinely typed/written
    without ё (it's optional in normal orthography), but Whisper's output
    tends to include it since that's the grammatically correct form - so a
    stop word saved as "орел" (as typed) against a transcription that comes
    back as "орёл" would otherwise differ by exactly one character, which
    for a short word already sits right at (or just under, with any other
    real-world STT noise on top) the similarity threshold. Same idea for
    Ukrainian і/ї is NOT handled here - that's a distinct-sound letter, not
    an optional-diacritic one, so folding it would hide real differences."""
    return word.replace("ё", "е")


def fuzzy_contains_phrase(text: str, phrase: str, *, threshold: float = PHRASE_SIMILARITY_THRESHOLD) -> bool:
    """True if some run of consecutive words in the longer of (`text`,
    `phrase`) fuzzy-matches the shorter one as a whole.

    Slides a window sized to whichever side has FEWER words across the
    other, rather than always sizing the window to `phrase` — that's what
    lets a short phrase ("да", "стоп") match correctly whether it's the
    entire utterance or just one word buried in a longer sentence ("да,
    давай, выключай"), AND (the direction that was missing) lets an
    utterance *shorter* than the stored phrase still match — e.g. a stop
    word saved as a full sentence during setup ("пусть будет тишина", 3
    words) still has to match the user later just saying the one word that
    matters ("тишина", 1 word). With a window always sized to the 3-word
    phrase, a 1-word utterance could never produce even one full-length
    window to compare — `range(1 - 3 + 1)` is empty — so it could never
    match at all, regardless of how close the wording was."""
    words = [_fold_yo(word) for word in re.findall(r"[\w']+", text.lower(), flags=re.UNICODE)]
    phrase_words = [_fold_yo(word) for word in phrase.lower().split()]
    if not words or not phrase_words:
        return False

    if len(words) >= len(phrase_words):
        longer, shorter = words, phrase_words
    else:
        longer, shorter = phrase_words, words

    window_size = len(shorter)
    shorter_joined = " ".join(shorter)
    return any(
        SequenceMatcher(None, " ".join(longer[start : start + window_size]), shorter_joined).ratio() >= threshold
        for start in range(len(longer) - window_size + 1)
    )


def fuzzy_matches_any(text: str, phrases: set[str] | tuple[str, ...], *, threshold: float = PHRASE_SIMILARITY_THRESHOLD) -> bool:
    return any(fuzzy_contains_phrase(text, phrase, threshold=threshold) for phrase in phrases)
