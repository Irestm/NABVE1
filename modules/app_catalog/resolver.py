from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from modules.app_catalog import catalog
from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.matching import shortlist_candidates

logger = get_logger(__name__)

# Below this, a resolution is treated as "not sure enough to act on
# silently" — the caller (core/voice/pipeline.py) asks "did you mean X?"
# instead of just launching it.
CONFIDENCE_THRESHOLD = 60

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ResolvedApp:
    app: InstalledApp
    confidence: int

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD


def _build_prompt(query: str, candidates: list[InstalledApp]) -> str:
    listing = "; ".join(f"{index}: {app.display_name}" for index, app in enumerate(candidates))
    return (
        f'Пользователь голосом попросил открыть приложение или игру. Распознавание речи могло исказить '
        f'название (например, фонетически исказить произношение иностранного слова). Он сказал: "{query}". '
        f"Вот пронумерованный список того, что реально установлено на этом компьютере: {listing}. "
        "Определи номер варианта, который вероятнее всего имелся в виду, и оцени уверенность от 0 до 100. "
        "Если ни один вариант совсем не подходит — верни null вместо номера. Ответь ТОЛЬКО JSON-объектом без "
        'пояснений, строго в формате {"index": <номер_или_null>, "confidence": <0-100>}.'
    )


def _parse_resolution(raw: str, candidates: list[InstalledApp]) -> ResolvedApp | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("App resolution returned no JSON object")
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("App resolution returned invalid JSON")
        return None

    index = parsed.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < len(candidates)):
        return None

    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None

    return ResolvedApp(app=candidates[index], confidence=max(0, min(100, int(confidence))))


async def resolve(query: str) -> ResolvedApp | None:
    """Tries to map `query` (the raw text captured after "открой"/"open" —
    see core/voice/intent.py's _OPEN_APP_PATTERNS) to one of the apps/games
    actually installed on this machine (modules.app_catalog.catalog).

    Tries candidate_chain()'s adapters in order (local model, then the
    ai_bridge cloud chain) — unlike routing an ordinary free-text question
    (core/voice/ai_router.py), there's no "is this complex" branch here,
    since resolving a niche game/app name is exactly the kind of thing the
    local model's knowledge is least likely to cover, and confidence (not
    adapter choice) is what decides whether to escalate to cloud: a
    confidence below CONFIDENCE_THRESHOLD from one adapter is treated like a
    failure and the next adapter is tried. If nothing reaches the threshold,
    the best guess seen (if any) is still returned: the caller uses
    ResolvedApp.is_confident to decide between launching it directly and
    asking "did you mean X?" first. Returns None only when there's nothing
    to offer at all (no installed-app candidates, or every adapter failed
    outright) — the caller's fallback in that case is to launch the raw
    spoken text exactly as it did before this feature existed."""
    query = query.strip()
    if not query:
        return None

    apps = catalog.list_installed_apps()
    candidates = shortlist_candidates(query, apps)
    if not candidates:
        return None

    prompt = _build_prompt(query, candidates)

    best: ResolvedApp | None = None
    for adapter in candidate_chain(query):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("App resolution adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        resolved = _parse_resolution(raw, candidates)
        if resolved is None:
            continue
        if best is None or resolved.confidence > best.confidence:
            best = resolved
        if resolved.is_confident:
            return resolved

    return best
