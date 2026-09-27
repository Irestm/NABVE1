from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from core.logger import get_logger
from modules.english_learning.domain import ItemKind, LexiconEntry
from modules.english_learning.expressions import LexiconMatcher, normalize_text, tokenize_expression
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

KAIKKI_BASE_URL = "https://kaikki.org/dictionary/English"
KAIKKI_DEFAULT_POS: tuple[str, ...] = ("phrase", "prep_phrase", "adv_phrase", "intj", "verb", "adv")
KAIKKI_EXTRA_POS: tuple[str, ...] = ("noun", "adj")
KAIKKI_ATTRIBUTION = "Wiktionary via kaikki.org (Tatu Ylonen, Wiktextract), CC BY-SA 4.0"
PARTICLES: frozenset[str] = frozenset(
    {
        "up", "out", "off", "on", "in", "down", "away", "back", "over", "through", "around", "round",
        "about", "along", "across", "by", "forward", "apart", "aside", "ahead", "together", "into", "onto",
    }
)
_ALLOWED = re.compile(r"^[A-Za-z][A-Za-z' -]*[A-Za-z]$")
_SKIP_TAGS: frozenset[str] = frozenset(
    {"obsolete", "archaic", "rare", "alt-of", "abbreviation", "initialism", "acronym", "misspelling", "form-of"}
)
_MAX_WORDS = 6
_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "from", "and", "or", "but", "is",
        "are", "was", "be", "it", "its", "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
        "this", "that", "these", "those", "as", "so", "if", "not", "no", "do", "does", "did", "'s", "all", "one",
    }
)
_BORROWING_TEMPLATES: frozenset[str] = frozenset({"bor", "bor+", "lbor", "der", "der+", "uder"})


def kaikki_url(pos: str) -> str:
    return f"{KAIKKI_BASE_URL}/pos-{pos}/kaikki.org-dictionary-English-by-pos-{pos}.jsonl"


def _sense_tags(entry: dict[str, Any]) -> list[set[str]]:
    return [set(sense.get("tags") or []) for sense in entry.get("senses") or [] if isinstance(sense, dict)]


def _is_foreign_borrowing(entry: dict[str, Any]) -> bool:
    for template in entry.get("etymology_templates") or []:
        if not isinstance(template, dict):
            continue
        name = str(template.get("name") or "")
        source = str((template.get("args") or {}).get("2") or "")
        if (name in _BORROWING_TEMPLATES or "borrowing" in name) and source not in ("", "en", "enm", "ang"):
            return True
    return False


def _is_phrasebook(entry: dict[str, Any]) -> bool:
    for sense in entry.get("senses") or []:
        for category in sense.get("categories") or [] if isinstance(sense, dict) else []:
            name = category.get("name", "") if isinstance(category, dict) else str(category)
            if "phrasebook" in name.lower():
                return True
    return False


def classify_entry(entry: dict[str, Any]) -> ItemKind | None:
    word = str(entry.get("word") or "").strip()
    if not _ALLOWED.match(word) or word[0].isupper():
        return None
    if _is_foreign_borrowing(entry) or _is_phrasebook(entry):
        return None
    parts = tokenize_expression(word)
    if not 2 <= len(parts) <= _MAX_WORDS or all(part in _FUNCTION_WORDS for part in parts):
        return None
    tags = _sense_tags(entry)
    usable = [sense for sense in tags if not sense & _SKIP_TAGS]
    if not usable:
        return None
    merged = set().union(*usable)
    pos = str(entry.get("pos") or "")
    if pos == "verb" and parts[1] in PARTICLES and len(parts) <= 3:
        return "phrasal_verb"
    if "slang" in merged:
        return "slang"
    if "idiomatic" in merged or pos in ("phrase", "prep_phrase", "adv_phrase", "intj"):
        return "idiom"
    return None


def entries_from_jsonl(lines: Iterable[str | bytes]) -> Iterator[LexiconEntry]:
    for raw in lines:
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("lang_code") not in (None, "en"):
            continue
        kind = classify_entry(entry)
        if kind is None:
            continue
        expression = " ".join(str(entry["word"]).split())
        yield LexiconEntry(
            expression=expression,
            normalized=normalize_text(expression),
            kind=kind,
            cefr=None,
            source="wiktionary",
        )


def store(entries: Iterable[LexiconEntry], uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> int:
    unique: dict[str, LexiconEntry] = {}
    for entry in entries:
        current = unique.get(entry.normalized)
        if current is None or (current.kind == "idiom" and entry.kind == "phrasal_verb"):
            unique[entry.normalized] = entry
    with uow_factory() as uow:
        count = uow.lexicon.replace_all(unique.values())
        uow.commit()
    _reset_cache()
    return count


_cache_lock = threading.Lock()
_cache: dict[str, tuple[int, LexiconMatcher]] = {}


def _reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


def load_matcher(uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> LexiconMatcher | None:
    with uow_factory() as uow:
        count = uow.lexicon.count()
        if count == 0:
            return None
        key = str(getattr(uow, "_db_path", ""))
        with _cache_lock:
            cached = _cache.get(key)
            if cached is not None and cached[0] == count:
                return cached[1]
        entries = uow.lexicon.list_all()
    matcher = LexiconMatcher(entries)
    with _cache_lock:
        _cache[key] = (count, matcher)
    logger.info("Loaded %d multi-word expressions for matching", len(matcher))
    return matcher
