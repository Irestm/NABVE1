from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.providers.base import AIResult, AllProvidersFailed, ChatMessage
from modules.ai_bridge.providers.router import get_router
from modules.english_learning.domain import Card, EpisodeWord, Example
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

BATCH_SIZE = 25
MAX_TRANSLATIONS = 3
_MAX_DEFINITION_CHARS = 240
_TOKENS_PER_WORD = 140
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)

MAX_SENSES = 3

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
                    "sense_label": {"type": ["string", "null"]},
                    "translations_ru": {"type": "array", "items": {"type": "string"}},
                    "definition_en": {"type": "string"},
                    "literal_translation": {"type": ["string", "null"]},
                    "example_index": {"type": ["integer", "null"]},
                },
                "required": [
                    "lemma",
                    "word",
                    "sense_label",
                    "translations_ru",
                    "definition_en",
                    "literal_translation",
                    "example_index",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You write vocabulary flashcards for a Russian-speaking learner who watches a TV series or a movie. "
    "Every input item has a lemma, its type and up to three numbered subtitle lines where it was used. "
    "Translate the item in the meaning it has IN THOSE LINES, never a generic dictionary meaning "
    "('run a company' is 'управлять', not 'бежать'). Return: lemma (exactly as given), word (the form to learn: "
    "the dictionary form of a word, or the base form of an expression such as 'give up'), translations_ru "
    "(1-3 short Russian translations for that meaning, best first), definition_en (one simple English sentence, "
    "no more than 20 words), literal_translation (word-by-word Russian for idioms, otherwise null), example_index "
    "(number of the line that shows this meaning). If the lines use the item in clearly different meanings, "
    "return one card per meaning (at most three) and give each a short Russian sense_label (1-2 words, e.g. "
    "'управлять', 'бежать'); otherwise return a single card with sense_label null."
)

Complete = Callable[[list[ChatMessage], dict[str, Any], int], Awaitable[AIResult]]


@dataclass(frozen=True)
class GenerationProgress:
    done: int
    total: int
    created: int
    skipped: int
    phase: str = "cards"


def _default_complete(messages: list[ChatMessage], schema: dict[str, Any], max_tokens: int) -> Awaitable[AIResult]:
    return get_router().complete(messages, json_schema=schema, max_tokens=max_tokens)


def _examples(word: EpisodeWord) -> list[Example]:
    return word.examples or [Example(text=word.example, timestamp_ms=word.timestamp_ms)]


def _batch_prompt(words: list[EpisodeWord]) -> str:
    lines: list[str] = []
    for word in words:
        kind = word.pos if word.kind == "word" else word.kind.replace("_", " ")
        numbered = " ".join(f"[{number}] {example.text}" for number, example in enumerate(_examples(word), start=1))
        lines.append(f"- lemma: {word.lemma} | type: {kind} | seen as: {word.surface} | lines: {numbered}")
    return "Items:\n" + "\n".join(lines)


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


def _optional_text(value: Any) -> str | None:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text or None


def _card(source: EpisodeWord, *, word: str, translations: list[str], definition: str, sense_label: str | None,
          literal: str | None, example: Example) -> Card:
    return Card(
        episode_id=source.episode_id,
        word=word,
        lemma=source.lemma,
        pos=source.pos,
        cefr=source.cefr,
        translations_ru=translations,
        definition_en=definition,
        example=example.text,
        timestamp_ms=example.timestamp_ms,
        category=source.category,
        kind=source.kind,
        surface_form=source.surface,
        sense_label=sense_label,
        literal_translation=literal if source.kind != "word" else None,
        cefr_source=source.cefr_source,
        confidence=source.confidence,
    )


def cards_from_reply(words: list[EpisodeWord], parsed: Any) -> list[Card]:
    by_lemma = {word.lemma.lower(): word for word in words}
    items = parsed.get("cards") if isinstance(parsed, dict) else None
    senses: dict[str, list[Card]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        lemma = str(item.get("lemma") or "").strip().lower()
        source = by_lemma.get(lemma)
        if source is None:
            continue
        translations = clean_translations(item.get("translations_ru"))
        definition = " ".join(str(item.get("definition_en") or "").split())[:_MAX_DEFINITION_CHARS]
        if not translations or not definition:
            continue
        label = _optional_text(item.get("sense_label"))
        existing = senses.setdefault(lemma, [])
        if existing:
            labels = [card.sense_label for card in existing]
            if len(existing) >= MAX_SENSES or label is None or None in labels or label.lower() in (
                (value or "").lower() for value in labels
            ):
                continue
        examples = _examples(source)
        index = item.get("example_index")
        example = examples[index - 1] if isinstance(index, int) and 1 <= index <= len(examples) else examples[0]
        word = " ".join(str(item.get("word") or "").split()) or source.lemma
        existing.append(
            _card(
                source,
                word=word,
                translations=translations,
                definition=definition,
                sense_label=label,
                literal=_optional_text(item.get("literal_translation")),
                example=example,
            )
        )
    cards: list[Card] = []
    for group in senses.values():
        if len(group) == 1:
            group[0].sense_label = None
        cards.extend(group)
    return cards


def prefilled_card(word: EpisodeWord) -> Card | None:
    details = word.details or {}
    translations = clean_translations(details.get("translations_ru"))
    definition = " ".join(str(details.get("meaning_en") or "").split())[:_MAX_DEFINITION_CHARS]
    if not translations or not definition:
        return None
    return _card(
        word,
        word=word.lemma,
        translations=translations,
        definition=definition,
        sense_label=None,
        literal=_optional_text(details.get("literal_translation")),
        example=_examples(word)[0],
    )


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
    ready = [card for word in pending if word.details and (card := prefilled_card(word)) is not None]
    if ready:
        with uow_factory() as uow:
            for card in ready:
                uow.cards.add(card)
            uow.commit()
        progress = GenerationProgress(done=len(ready), total=progress.total, created=len(ready), skipped=0)
        if on_progress is not None:
            on_progress(progress)
    prefilled = {card.lemma for card in ready}
    pending = [word for word in pending if word.lemma not in prefilled]
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
