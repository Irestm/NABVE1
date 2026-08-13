from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from modules.app_catalog.domain import InstalledApp

# A garbled voice query like "дед селс" for "Dead Cells" shares zero
# characters with the Latin app name it's supposed to match — Cyrillic
# phonetic transliteration of a foreign title isn't a spelling variant, it's
# a different alphabet. Plain SequenceMatcher would score every such pair at
# ~0, which is exactly the case this whole feature exists to handle, so the
# query is also compared against this rough phonetic transliteration before
# scoring. It doesn't need to be linguistically perfect — just close enough
# that "ded sels" shares meaningfully more characters with "dead cells" than
# "дед селс" ever could, so the real match survives into the shortlist.
_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Below this score, the shortlist ranking isn't trusted at all — safer to
# hand the AI step an arbitrary bounded slice of installed apps than a
# ranking that might have already filtered the right answer out.
_MIN_USEFUL_SCORE = 0.3


def transliterate(text: str) -> str:
    return "".join(_CYRILLIC_TO_LATIN.get(char, char) for char in text.lower())


def shortlist_candidates(query: str, apps: Sequence[InstalledApp], limit: int = 15) -> list[InstalledApp]:
    """Cheaply narrows potentially hundreds of installed apps down to the
    `limit` most plausible matches for `query`, before any of them are sent
    to an AI adapter — necessary both for prompt size and, more importantly,
    so a single "open X" doesn't leak the user's entire software inventory
    to a third-party cloud provider (see modules.ai_bridge.provider_manager)
    every time. Intentionally crude (SequenceMatcher over raw + transliterated
    text, no real phonetics) — the actual "is this really what they meant"
    judgment call is left entirely to the AI resolution step that follows;
    this step only needs to not accidentally drop the right answer."""
    apps = list(apps)
    if len(apps) <= limit:
        return apps

    normalized_query = query.strip().lower()
    transliterated_query = transliterate(normalized_query)

    scored: list[tuple[float, InstalledApp]] = []
    for app in apps:
        candidate = app.display_name.lower()
        score = max(
            SequenceMatcher(None, normalized_query, candidate).ratio(),
            SequenceMatcher(None, transliterated_query, candidate).ratio(),
        )
        scored.append((score, app))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored[0][0] < _MIN_USEFUL_SCORE:
        return apps[:limit]
    return [app for _, app in scored[:limit]]
