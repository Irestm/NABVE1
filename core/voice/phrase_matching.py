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


# Phonetic Cyrillic -> Latin transliteration, used only to give short words
# a second chance at matching (see _transliterate below) - not meant to be a
# complete/correct transliteration standard, just close enough for
# SequenceMatcher on words a few letters long.
_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _transliterate(word: str) -> str:
    """Maps Cyrillic letters to a rough phonetic Latin spelling and leaves
    everything else (including letters already Latin) untouched."""
    return "".join(_CYRILLIC_TO_LATIN.get(letter, letter) for letter in word)


def with_transliterated_variant(phrase: str) -> tuple[str, ...]:
    """Returns (phrase,) or, if `phrase` contains Cyrillic, (phrase,
    transliterated) - an extra Latin-spelled candidate for callers that fuzzy-
    match a single configured word/short phrase against freshly transcribed
    text (see core/voice/special_phrases.py's stop word, the only current
    caller).

    Deliberately NOT built into fuzzy_contains_phrase/fuzzy_matches_any
    themselves: those are shared by core/voice/intent.py for shutdown/
    restart/media/messaging/etc. trigger words, compared against whole
    sentences via a sliding window - transliterating every window there
    (tried and reverted) skews SequenceMatcher's length-based ratio just
    enough, on some multi-character mappings (ж->zh, ш->sh, щ->shch), to
    push unrelated same-script pairs like "включи"/"выключи" over threshold
    that weren't before, breaking youtube/spotify/shutdown trigger
    matching. Adding one extra whole-phrase candidate here instead - rather
    than changing how any comparison is scored - carries none of that risk.

    Why this is needed at all: Whisper's language detection is unreliable
    on a single short word said in isolation - a stop word configured as
    "стоп" regularly comes back transcribed as the Latin "Stop" instead,
    which fuzzy_contains_phrase's character-level comparison never matched
    (Cyrillic and Latin letters share no codepoints even when they sound
    identical, so the ratio sat at ~0 regardless of pronunciation)."""
    translit = _transliterate(phrase)
    if translit == phrase:
        return (phrase,)
    return (phrase, translit)


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
