from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.providers.base import AIResult, AllProvidersFailed, ChatMessage
from modules.ai_bridge.providers.router import get_router
from modules.english_learning.domain import Card, EpisodeWord
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

BATCH_SIZE = 25
MAX_TRANSLATIONS = 3
_MAX_DEFINITION_CHARS = 240
_TOKENS_PER_WORD = 90
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)

CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lemma": {"type": "string"},
                    "word": {"type": "string"},
                    "translations_ru": {"type": "array", "items": {"type": "string"}},
                    "definition_en": {"type": "string"},
                },
                "required": ["lemma", "word", "translations_ru", "definition_en"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You write vocabulary flashcards for a Russian-speaking learner at A2-B1 level who watches a TV series. "
    "For every input word return one card: lemma (exactly as given), word (the dictionary form to learn, e.g. "
    "'figure out' only if the example clearly uses the phrasal verb, otherwise the lemma), translations_ru "
    "(1-3 short Russian translations that fit the meaning in the example line, most likely first), "
    "definition_en (one simple English sentence, A2 vocabulary, no more than 20 words)."
)

Complete = Callable[[list[ChatMessage], dict[str, Any], int], Awaitable[AIResult]]


@dataclass(frozen=True)
class GenerationProgress:
    done: int
    total: int
    created: int
    skipped: int


def _default_complete(messages: list[ChatMessage], schema: dict[str, Any], max_tokens: int) -> Awaitable[AIResult]:
    return get_router().complete(messages, json_schema=schema, max_tokens=max_tokens)


def _batch_prompt(words: list[EpisodeWord]) -> str:
    lines = [f"- lemma: {word.lemma} | pos: {word.pos} | seen as: {word.surface} | line: {word.example}" for word in words]
    return "Words:\n" + "\n".join(lines)


def clean_translations(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = " ".join(value.strip().strip(".;,").split())
        if text and _CYRILLIC.search(text) and text.lower() not in (item.lower() for item in cleaned):
            cleaned.append(text)
    return cleaned[:MAX_TRANSLATIONS]


def cards_from_reply(words: list[EpisodeWord], parsed: Any) -> list[Card]:
    by_lemma = {word.lemma.lower(): word for word in words}
    items = parsed.get("cards") if isinstance(parsed, dict) else None
    cards: list[Card] = []
    used: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        lemma = str(item.get("lemma") or "").strip().lower()
        source = by_lemma.get(lemma)
        if source is None or lemma in used:
            continue
        translations = clean_translations(item.get("translations_ru"))
        definition = " ".join(str(item.get("definition_en") or "").split())[:_MAX_DEFINITION_CHARS]
        if not translations or not definition:
            continue
        word = " ".join(str(item.get("word") or "").split()) or source.lemma
        used.add(lemma)
        cards.append(
            Card(
                episode_id=source.episode_id,
                word=word,
                lemma=source.lemma,
                pos=source.pos,
                cefr=source.cefr,
                translations_ru=translations,
                definition_en=definition,
                example=source.example,
                timestamp_ms=source.timestamp_ms,
                category=source.category,
            )
        )
    return cards


async def _generate_batch(batch: list[EpisodeWord], complete: Complete) -> list[Card]:
    max_tokens = max(1000, len(batch) * _TOKENS_PER_WORD)
    cards: list[Card] = []
    remaining = batch
    for _attempt in range(2):
        messages: list[ChatMessage] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _batch_prompt(remaining)},
        ]
        result = await complete(messages, CARD_SCHEMA, max_tokens)
        cards.extend(cards_from_reply(remaining, result.parsed_json))
        covered = {card.lemma for card in cards}
        remaining = [word for word in batch if word.lemma not in covered]
        if not remaining:
            break
    if remaining:
        logger.warning("No valid card for %d words: %s", len(remaining), ", ".join(word.lemma for word in remaining))
    return cards


async def generate_cards(
    episode_id: int,
    *,
    complete: Complete = _default_complete,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    on_progress: Callable[[GenerationProgress], None] | None = None,
    batch_size: int = BATCH_SIZE,
) -> GenerationProgress:
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        existing = uow.cards.existing_keys(episode_id)
        pending = [word for word in uow.words.list_for_episode(episode_id) if (word.lemma, word.pos) not in existing]
    progress = GenerationProgress(done=0, total=len(pending), created=0, skipped=0)
    if on_progress is not None:
        on_progress(progress)
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        try:
            cards = await _generate_batch(batch, complete)
        except AllProvidersFailed:
            logger.exception("Card generation stopped: no AI provider answered")
            raise
        with uow_factory() as uow:
            for card in cards:
                uow.cards.add(card)
            uow.commit()
        progress = GenerationProgress(
            done=progress.done + len(batch),
            total=progress.total,
            created=progress.created + len(cards),
            skipped=progress.skipped + len(batch) - len(cards),
        )
        if on_progress is not None:
            on_progress(progress)
    return progress
