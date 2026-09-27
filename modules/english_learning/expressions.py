from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from modules.english_learning.domain import (
    CEFR_LEVELS,
    MWE_POS,
    AiExpression,
    CefrSource,
    Example,
    ItemKind,
    LexiconEntry,
    SubtitleCue,
    WordCandidate,
)
from modules.english_learning.language_filter import CueLanguage
from modules.english_learning.lemmatizer import AnalyzedToken
from modules.english_learning.word_selection import MAX_EXAMPLES, trim_example

HitSource = Literal["spacy", "lexicon", "ai"]

PARTICLE_DEP = "prt"
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*|'[a-z]+")
_PUNCT = re.compile(r"[^\w\s']+")
_SPACES = re.compile(r"\s+")
_WILDCARDS: dict[str, int] = {
    "someone": 3,
    "somebody": 3,
    "something": 3,
    "sb": 3,
    "sth": 3,
    "one's": 1,
    "someone's": 1,
    "oneself": 1,
}
_WILDCARD_FORMS: dict[str, tuple[str, ...]] = {
    "one's": ("my", "your", "his", "her", "its", "our", "their"),
    "someone's": ("my", "your", "his", "her", "its", "our", "their"),
    "oneself": ("myself", "yourself", "himself", "herself", "itself", "ourselves", "yourselves", "themselves"),
}
_KIND_PRIORITY: dict[HitSource, int] = {"lexicon": 0, "ai": 1, "spacy": 2}
MAX_EXPRESSION_TOKENS = 8


def normalize_text(text: str) -> str:
    folded = text.lower().replace("’", "'").replace("‘", "'")
    folded = _PUNCT.sub(" ", folded)
    return _SPACES.sub(" ", folded).strip(" '")


def tokenize_expression(text: str) -> list[str]:
    folded = text.lower().replace("’", "'")
    return _TOKEN.findall(folded)


def surface_in_line(surface: str, line: str) -> bool:
    needle = normalize_text(surface)
    if not needle:
        return False
    haystack = f" {normalize_text(line)} "
    return f" {needle} " in haystack


@dataclass(frozen=True)
class ExpressionHit:
    normalized: str
    surface_form: str
    kind: ItemKind
    cue_index: int
    token_indices: tuple[int, ...]
    source: HitSource
    cefr: str | None = None
    confidence: float | None = None
    details: dict[str, Any] | None = None


def _surface(tokens: Sequence[AnalyzedToken], indices: Iterable[int]) -> str:
    ordered = sorted(indices)
    return " ".join(tokens[i].text for i in range(ordered[0], ordered[-1] + 1)).replace(" '", "'").replace(" n't", "n't")


def phrasal_verbs(cue: SubtitleCue, tokens: Sequence[AnalyzedToken]) -> list[ExpressionHit]:
    hits: list[ExpressionHit] = []
    for index, token in enumerate(tokens):
        if token.dep != PARTICLE_DEP or not 0 <= token.head < len(tokens):
            continue
        verb = tokens[token.head]
        if verb.pos != "VERB" or not verb.is_alpha or not token.is_alpha:
            continue
        indices = (token.head, index)
        hits.append(
            ExpressionHit(
                normalized=f"{verb.lemma.lower()} {token.text.lower()}",
                surface_form=_surface(tokens, indices),
                kind="phrasal_verb",
                cue_index=cue.index,
                token_indices=indices,
                source="spacy",
            )
        )
    return hits


@dataclass
class _Pattern:
    entry: LexiconEntry
    parts: list[str]


def pattern_parts(expression: str) -> list[str]:
    parts: list[str] = []
    for part in tokenize_expression(expression):
        if part == "'s" and parts and f"{parts[-1]}'s" in _WILDCARDS:
            parts[-1] = f"{parts[-1]}'s"
        else:
            parts.append(part)
    return parts


class LexiconMatcher:
    def __init__(self, entries: Iterable[LexiconEntry]) -> None:
        self._by_first: dict[str, list[_Pattern]] = {}
        for entry in entries:
            parts = pattern_parts(entry.expression)
            if len(parts) < 2 or len(parts) > MAX_EXPRESSION_TOKENS or parts[0] in _WILDCARDS:
                continue
            self._by_first.setdefault(parts[0], []).append(_Pattern(entry, parts))

    def __len__(self) -> int:
        return sum(len(items) for items in self._by_first.values())

    @staticmethod
    def _token_keys(token: AnalyzedToken) -> set[str]:
        return {token.lemma.lower().replace("’", "'"), token.text.lower().replace("’", "'")}

    def _match_from(self, parts: list[str], tokens: Sequence[AnalyzedToken], start: int) -> list[int] | None:
        def walk(part_index: int, token_index: int, used: list[int]) -> list[int] | None:
            if part_index == len(parts):
                return used
            if token_index >= len(tokens):
                return None
            part = parts[part_index]
            if part in _WILDCARDS:
                forms = _WILDCARD_FORMS.get(part)
                for width in range(1, _WILDCARDS[part] + 1):
                    span = tokens[token_index : token_index + width]
                    if len(span) < width or any(not item.is_alpha for item in span):
                        break
                    if forms is not None and span[0].text.lower() not in forms:
                        break
                    found = walk(part_index + 1, token_index + width, used)
                    if found is not None:
                        return found
                return None
            if part not in self._token_keys(tokens[token_index]):
                return None
            return walk(part_index + 1, token_index + 1, [*used, token_index])

        return walk(0, start, [])

    def find(self, cue: SubtitleCue, tokens: Sequence[AnalyzedToken]) -> list[ExpressionHit]:
        hits: list[ExpressionHit] = []
        for start, token in enumerate(tokens):
            candidates: list[_Pattern] = []
            for key in self._token_keys(token):
                candidates.extend(self._by_first.get(key, []))
            for pattern in sorted(candidates, key=lambda item: -len(item.parts)):
                matched = self._match_from(pattern.parts, tokens, start)
                if matched is None:
                    continue
                hits.append(
                    ExpressionHit(
                        normalized=pattern.entry.normalized,
                        surface_form=_surface(tokens, matched),
                        kind=pattern.entry.kind,
                        cue_index=cue.index,
                        token_indices=tuple(matched),
                        source="lexicon",
                        cefr=pattern.entry.cefr,
                    )
                )
                break
        return hits


def locate(surface: str, tokens: Sequence[AnalyzedToken]) -> tuple[int, ...] | None:
    wanted = tokenize_expression(surface)
    if not wanted:
        return None
    texts = [token.text.lower().replace("’", "'") for token in tokens]
    for start in range(len(texts) - len(wanted) + 1):
        if texts[start : start + len(wanted)] == wanted:
            return tuple(range(start, start + len(wanted)))
    joined = normalize_text(surface).split()
    for start in range(len(texts)):
        collected: list[int] = []
        rebuilt = ""
        for index in range(start, len(texts)):
            rebuilt += texts[index]
            collected.append(index)
            if rebuilt == "".join(joined):
                return tuple(i for i in collected if tokens[i].is_alpha or texts[i].startswith("'"))
            if not "".join(joined).startswith(rebuilt):
                break
    return None


def ai_hits(
    items: Iterable[AiExpression], cues_by_index: dict[int, SubtitleCue], tokens_by_index: dict[int, list[AnalyzedToken]]
) -> list[ExpressionHit]:
    hits: list[ExpressionHit] = []
    for item in items:
        cue = cues_by_index.get(item.cue_index)
        if cue is None or not surface_in_line(item.surface_form, cue.text):
            continue
        indices = locate(item.surface_form, tokens_by_index.get(item.cue_index, []))
        hits.append(
            ExpressionHit(
                normalized=item.normalized,
                surface_form=item.surface_form,
                kind=item.kind,
                cue_index=item.cue_index,
                token_indices=indices or (),
                source="ai",
                cefr=item.cefr_estimate,
                confidence=item.confidence,
                details={
                    "meaning_en": item.meaning_en,
                    "translations_ru": list(item.translations_ru),
                    "literal_translation": item.literal_translation,
                },
            )
        )
    return hits


@dataclass
class _Merged:
    normalized: str
    kind: ItemKind
    kind_source: HitSource
    cefr: str | None
    cefr_source: CefrSource | None
    confidence: float | None
    details: dict[str, Any] | None
    occurrences: list[tuple[SubtitleCue, str]] = field(default_factory=list)
    seen_cues: set[int] = field(default_factory=set)


def _valid_level(level: str | None) -> str | None:
    return level if level in CEFR_LEVELS else None


def merge_hits(hits: Iterable[ExpressionHit], cues_by_index: dict[int, SubtitleCue]) -> list[WordCandidate]:
    merged: dict[str, _Merged] = {}
    for hit in hits:
        cue = cues_by_index.get(hit.cue_index)
        if cue is None:
            continue
        item = merged.get(hit.normalized)
        if item is None:
            item = _Merged(
                normalized=hit.normalized,
                kind=hit.kind,
                kind_source=hit.source,
                cefr=None,
                cefr_source=None,
                confidence=None,
                details=None,
            )
            merged[hit.normalized] = item
        if _KIND_PRIORITY[hit.source] < _KIND_PRIORITY[item.kind_source]:
            item.kind = hit.kind
            item.kind_source = hit.source
        level = _valid_level(hit.cefr)
        if level is not None:
            if hit.source == "lexicon" and item.cefr_source != "lexicon":
                item.cefr, item.cefr_source = level, "lexicon"
            elif hit.source == "ai" and item.cefr_source is None:
                item.cefr, item.cefr_source = level, "ai"
        if hit.confidence is not None:
            item.confidence = max(item.confidence or 0.0, hit.confidence)
        if hit.details is not None and item.details is None:
            item.details = hit.details
        if hit.cue_index not in item.seen_cues:
            item.seen_cues.add(hit.cue_index)
            item.occurrences.append((cue, hit.surface_form))

    candidates: list[WordCandidate] = []
    for item in merged.values():
        occurrences = sorted(item.occurrences, key=lambda pair: pair[0].start_ms)
        examples: list[Example] = []
        for cue, surface in occurrences:
            text = trim_example(cue.text, surface.split()[0])
            if len(examples) < MAX_EXAMPLES and all(example.text != text for example in examples):
                examples.append(Example(text=text, timestamp_ms=cue.start_ms, cue_index=cue.index))
        first_cue, first_surface = occurrences[0]
        candidates.append(
            WordCandidate(
                lemma=item.normalized,
                pos=MWE_POS,
                cefr=item.cefr,
                category="core" if item.cefr is not None else "extra",
                count=len(occurrences),
                example=examples[0].text if examples else first_cue.text,
                timestamp_ms=first_cue.start_ms,
                surface=first_surface,
                kind=item.kind,
                examples=tuple(examples),
                cefr_source=item.cefr_source,
                confidence=item.confidence,
                details=item.details,
            )
        )
    candidates.sort(key=lambda candidate: candidate.timestamp_ms)
    return candidates


@dataclass(frozen=True)
class ExpressionScan:
    candidates: list[WordCandidate]
    consumed: frozenset[tuple[int, int]]
    hits: list[ExpressionHit]


def scan_expressions(
    cues: Sequence[SubtitleCue],
    analyzed: Sequence[list[AnalyzedToken]],
    *,
    languages: Sequence[CueLanguage] | None = None,
    lexicon: LexiconMatcher | None = None,
    ai_expressions: Sequence[AiExpression] = (),
) -> ExpressionScan:
    hits: list[ExpressionHit] = []
    cues_by_index: dict[int, SubtitleCue] = {}
    tokens_by_index: dict[int, list[AnalyzedToken]] = {}
    for position, (cue, tokens) in enumerate(zip(cues, analyzed)):
        cues_by_index[cue.index] = cue
        tokens_by_index[cue.index] = list(tokens)
        if languages is not None and languages[position] == "foreign":
            continue
        hits.extend(phrasal_verbs(cue, tokens))
        if lexicon is not None:
            hits.extend(lexicon.find(cue, tokens))
    accepted_ai = ai_hits(ai_expressions, cues_by_index, tokens_by_index)
    hits.extend(accepted_ai)
    if accepted_ai:
        adhoc = LexiconMatcher(
            LexiconEntry(expression=hit.normalized, normalized=hit.normalized, kind=hit.kind, cefr=None, source="ai")
            for hit in accepted_ai
        )
        known = {(hit.normalized, hit.cue_index) for hit in hits}
        for position, (cue, tokens) in enumerate(zip(cues, analyzed)):
            if languages is not None and languages[position] == "foreign":
                continue
            for hit in adhoc.find(cue, tokens):
                if (hit.normalized, hit.cue_index) not in known:
                    hits.append(
                        ExpressionHit(
                            normalized=hit.normalized,
                            surface_form=hit.surface_form,
                            kind=hit.kind,
                            cue_index=hit.cue_index,
                            token_indices=hit.token_indices,
                            source="ai",
                        )
                    )
    consumed = frozenset((hit.cue_index, index) for hit in hits for index in hit.token_indices)
    return ExpressionScan(candidates=merge_hits(hits, cues_by_index), consumed=consumed, hits=hits)
