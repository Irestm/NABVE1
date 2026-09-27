from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.providers.base import AIResult, ChatMessage
from modules.ai_bridge.providers.router import get_router
from modules.english_learning.card_generation import clean_translations
from modules.english_learning.domain import CEFR_LEVELS, EXPRESSION_KINDS, AiExpression, SubtitleCue
from modules.english_learning.expressions import normalize_text, surface_in_line
from modules.english_learning.language_filter import CueLanguage

logger = get_logger(__name__)

CHUNK_SIZE = 40
CHUNK_OVERLAP = 5
MIN_CONFIDENCE = 0.6
_MAX_TOKENS = 3000
_MAX_MEANING_CHARS = 240

EXPRESSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "surface_form": {"type": "string"},
                    "normalized": {"type": "string"},
                    "line_index": {"type": "integer"},
                    "kind": {"type": "string", "enum": sorted(EXPRESSION_KINDS)},
                    "meaning_en": {"type": "string"},
                    "translation_ru": {"type": "array", "items": {"type": "string"}},
                    "literal_translation": {"type": ["string", "null"]},
                    "cefr_estimate": {"type": ["string", "null"], "enum": [*CEFR_LEVELS, None]},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "surface_form",
                    "normalized",
                    "line_index",
                    "kind",
                    "meaning_en",
                    "translation_ru",
                    "literal_translation",
                    "cefr_estimate",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["expressions"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You find multi-word expressions in English TV/movie subtitles for a Russian-speaking learner. "
    "Look for phrasal verbs (give up, figure it out), idioms (break a leg), strong collocations whose meaning "
    "differs from word-by-word translation (run a company = управлять компанией) and slang (what's up). "
    "Ignore free word combinations with a literal meaning. For every expression return: surface_form exactly as "
    "written in the line, normalized dictionary form (base verb form, e.g. 'give up', 'break a leg'), "
    "line_index (the number in square brackets), kind, meaning_en (one simple sentence), translation_ru "
    "(1-3 Russian translations that fit THIS context), literal_translation (word-by-word Russian for idioms, "
    "otherwise null), cefr_estimate (A1-C2 or null) and confidence from 0 to 1. Do not invent expressions that "
    "are not in the lines."
)

Complete = Callable[[list[ChatMessage], dict[str, Any], int], Awaitable[AIResult]]


def _default_complete(messages: list[ChatMessage], schema: dict[str, Any], max_tokens: int) -> Awaitable[AIResult]:
    return get_router().complete(messages, json_schema=schema, max_tokens=max_tokens)


def chunk_cues(cues: Sequence[SubtitleCue], size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[list[SubtitleCue]]:
    if not cues:
        return []
    step = max(1, size - overlap)
    chunks: list[list[SubtitleCue]] = []
    for start in range(0, len(cues), step):
        chunks.append(list(cues[start : start + size]))
        if start + size >= len(cues):
            break
    return chunks


def _chunk_prompt(chunk: Sequence[SubtitleCue]) -> str:
    return "Lines:\n" + "\n".join(f"[{cue.index}] {cue.text}" for cue in chunk)


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def validate_reply(parsed: Any, chunk: Sequence[SubtitleCue]) -> list[AiExpression]:
    by_index = {cue.index: cue for cue in chunk}
    items = parsed.get("expressions") if isinstance(parsed, dict) else None
    accepted: list[AiExpression] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        surface = " ".join(str(item.get("surface_form") or "").split())
        line_index = item.get("line_index")
        cue = by_index.get(line_index) if isinstance(line_index, int) else None
        if cue is None or not surface_in_line(surface, cue.text):
            logger.warning("Dropped hallucinated expression %r (line %r)", surface, line_index)
            continue
        confidence = _confidence(item.get("confidence"))
        if confidence is None or confidence < MIN_CONFIDENCE:
            continue
        kind = str(item.get("kind") or "")
        if kind not in EXPRESSION_KINDS:
            continue
        normalized = normalize_text(str(item.get("normalized") or "")) or normalize_text(surface)
        if len(normalized.split()) < 2 and kind != "slang":
            continue
        translations = clean_translations(item.get("translation_ru"))
        meaning = " ".join(str(item.get("meaning_en") or "").split())[:_MAX_MEANING_CHARS]
        if not translations or not meaning:
            continue
        literal = item.get("literal_translation")
        level = item.get("cefr_estimate")
        accepted.append(
            AiExpression(
                cue_index=cue.index,
                surface_form=surface,
                normalized=normalized,
                kind=kind,
                meaning_en=meaning,
                translations_ru=translations,
                literal_translation=" ".join(str(literal).split()) if isinstance(literal, str) and literal.strip() else None,
                cefr_estimate=level if level in CEFR_LEVELS else None,
                confidence=min(1.0, confidence),
            )
        )
    return accepted


async def find_expressions(
    cues: Sequence[SubtitleCue],
    *,
    languages: Sequence[CueLanguage] | None = None,
    complete: Complete = _default_complete,
    on_chunk: Callable[[int, int], None] | None = None,
) -> list[AiExpression]:
    english = [cue for position, cue in enumerate(cues) if languages is None or languages[position] != "foreign"]
    chunks = chunk_cues(english)
    found: dict[tuple[str, int], AiExpression] = {}
    for number, chunk in enumerate(chunks, start=1):
        messages: list[ChatMessage] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _chunk_prompt(chunk)},
        ]
        result = await complete(messages, EXPRESSION_SCHEMA, _MAX_TOKENS)
        for item in validate_reply(result.parsed_json, chunk):
            key = (item.normalized, item.cue_index)
            current = found.get(key)
            if current is None or item.confidence > current.confidence:
                found[key] = item
        if on_chunk is not None:
            on_chunk(number, len(chunks))
    return sorted(found.values(), key=lambda item: (item.cue_index, item.normalized))
