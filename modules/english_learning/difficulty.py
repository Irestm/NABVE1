from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from modules.english_learning.domain import CEFR_LEVELS, EpisodeStats, Title
from modules.english_learning.repository import LemmaRecord
from modules.english_learning.stats import UNLEVELED
from modules.english_learning.uow import EnglishUnitOfWork

Verdict = Literal["Подходит", "Подходит с усилием", "Пока рано"]
VERDICTS: tuple[Verdict, ...] = ("Подходит", "Подходит с усилием", "Пока рано")

COMFORT_COVERAGE = 0.98
EFFORT_COVERAGE = 0.95
FAST_SPEECH_WPM = 180.0
HIGH_SLANG_PER_1000 = 8.0
NOTABLE_FOREIGN_SHARE = 0.05
HIGH_OFF_LIST_SHARE = 0.08
BORDERLINE_MARGIN = 0.01
FREQUENT_MISTAKES = 2
EXAMPLE_LIMIT = 5
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class KnownWords:
    user_level: str
    lemmas_by_level_limit: frozenset[str]
    struggling: frozenset[str]
    learned: frozenset[str]

    def knows(self, lemma: str, level: str | None) -> bool:
        if lemma in self.learned:
            return True
        if lemma in self.struggling:
            return False
        return level is not None and level in self.lemmas_by_level_limit


def known_words(user_level: str, records: Iterable[LemmaRecord]) -> KnownWords:
    index = CEFR_LEVELS.index(user_level) if user_level in CEFR_LEVELS else CEFR_LEVELS.index("B1")
    struggling: set[str] = set()
    learned: set[str] = set()
    for record in records:
        if record.wrong >= FREQUENT_MISTAKES and record.wrong > record.correct:
            struggling.add(record.lemma)
        elif record.learned:
            learned.add(record.lemma)
    return KnownWords(
        user_level=CEFR_LEVELS[index],
        lemmas_by_level_limit=frozenset(CEFR_LEVELS[: index + 1]),
        struggling=frozenset(struggling),
        learned=frozenset(learned),
    )


def coverage(lemma_counts: dict[str, int], lemma_levels: dict[str, str | None], known: KnownWords) -> float:
    total = sum(lemma_counts.values())
    if total == 0:
        return 0.0
    covered = sum(count for lemma, count in lemma_counts.items() if known.knows(lemma, lemma_levels.get(lemma)))
    return covered / total


def base_verdict(value: float) -> Verdict:
    if value >= COMFORT_COVERAGE:
        return "Подходит"
    if value >= EFFORT_COVERAGE:
        return "Подходит с усилием"
    return "Пока рано"


@dataclass(frozen=True)
class DifficultyReport:
    title: str
    kind: str
    year: int | None
    title_id: int | None
    episodes_analyzed: int
    coverage: float
    verdict: Verdict
    base_verdict: Verdict
    user_level: str
    words_per_minute: float
    slang_per_1000: float
    non_english_share: float
    off_list_share: float
    above_level_count: int
    examples: list[str]
    distribution: dict[str, int]
    factors: list[str] = field(default_factory=list)
    small_sample: bool = False
    has_cards: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "kind": self.kind,
            "year": self.year,
            "title_id": self.title_id,
            "episodes_analyzed": self.episodes_analyzed,
            "coverage": round(self.coverage, 4),
            "verdict": self.verdict,
            "base_verdict": self.base_verdict,
            "user_level": self.user_level,
            "words_per_minute": self.words_per_minute,
            "slang_per_1000": self.slang_per_1000,
            "non_english_share": self.non_english_share,
            "off_list_share": self.off_list_share,
            "above_level_count": self.above_level_count,
            "examples": self.examples,
            "distribution": self.distribution,
            "factors": self.factors,
            "small_sample": self.small_sample,
            "has_cards": self.has_cards,
            "source": "subtitles",
        }


def _factors(wpm: float, slang: float, foreign: float, off_list: float) -> list[str]:
    factors: list[str] = []
    if wpm > FAST_SPEECH_WPM:
        factors.append(f"быстрая речь — {wpm:.0f} слов/мин")
    if slang > HIGH_SLANG_PER_1000:
        factors.append(f"много сленга и идиом — {slang:.1f} на 1000 слов")
    if foreign >= NOTABLE_FOREIGN_SHARE:
        factors.append(f"реплики не на английском — {foreign * 100:.0f}%")
    if off_list > HIGH_OFF_LIST_SHARE:
        factors.append(f"много слов вне CEFR-списков (термины, устаревшая лексика) — {off_list * 100:.0f}%")
    return factors


def adjusted_verdict(value: float, factors: list[str]) -> Verdict:
    verdict = base_verdict(value)
    if not factors or verdict == "Пока рано":
        return verdict
    threshold = COMFORT_COVERAGE if verdict == "Подходит" else EFFORT_COVERAGE
    if len(factors) >= 2 or value - threshold < BORDERLINE_MARGIN:
        return VERDICTS[VERDICTS.index(verdict) + 1]
    return verdict


def build_report(title: Title, stats: list[EpisodeStats], known: KnownWords, *, has_cards: bool = False) -> DifficultyReport:
    lemma_counts: Counter[str] = Counter()
    lemma_levels: dict[str, str | None] = {}
    distribution: Counter[str] = Counter()
    tokens = minutes = spoken = slang = foreign_cues = cues = off_list_tokens = 0.0
    for item in stats:
        lemma_counts.update(item.lemma_counts)
        lemma_levels.update(item.lemma_levels)
        distribution.update(item.tokens_by_level)
        tokens += item.token_count
        minutes += item.speech_minutes
        spoken += item.words_per_minute * item.speech_minutes
        slang += item.slang_count + item.idiom_count
        foreign_cues += item.non_english_cues
        cues += item.cue_count
        off_list_tokens += item.tokens_by_level.get(UNLEVELED, 0)
    value = coverage(dict(lemma_counts), lemma_levels, known)
    limit = CEFR_LEVELS.index(known.user_level)
    above = [
        lemma
        for lemma, _count in lemma_counts.most_common()
        if not known.knows(lemma, lemma_levels.get(lemma))
        and (level := lemma_levels.get(lemma)) is not None
        and CEFR_LEVELS.index(level) > limit
    ]
    wpm = round(spoken / minutes, 1) if minutes else 0.0
    slang_rate = round(slang / tokens * 1000, 2) if tokens else 0.0
    foreign = round(foreign_cues / cues, 4) if cues else 0.0
    off_list = round(off_list_tokens / tokens, 4) if tokens else 0.0
    factors = _factors(wpm, slang_rate, foreign, off_list)
    return DifficultyReport(
        title=title.name,
        kind=title.kind,
        year=title.year,
        title_id=title.id,
        episodes_analyzed=len(stats),
        coverage=value,
        verdict=adjusted_verdict(value, factors),
        base_verdict=base_verdict(value),
        user_level=known.user_level,
        words_per_minute=wpm,
        slang_per_1000=slang_rate,
        non_english_share=foreign,
        off_list_share=off_list,
        above_level_count=len(above),
        examples=above[:EXAMPLE_LIMIT],
        distribution={level: int(distribution.get(level, 0)) for level in (*CEFR_LEVELS, UNLEVELED)},
        factors=factors,
        small_sample=title.kind == "series" and len(stats) <= 1,
        has_cards=has_cards,
    )


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower().replace("&", "and")))


def find_title(titles: Iterable[Title], name: str, year: int | None = None, kind: str | None = None) -> Title | None:
    wanted = _normalize(name)
    if not wanted:
        return None
    candidates = [title for title in titles if kind in (None, "unknown", title.kind)]
    exact = [title for title in candidates if _normalize(title.name) == wanted]
    partial = [title for title in candidates if wanted in _normalize(title.name) or _normalize(title.name) in wanted]
    for group in (exact, partial):
        if year is not None:
            dated = [title for title in group if title.year == year]
            if dated:
                return dated[0]
        if group:
            return group[0]
    return None


def title_report(
    name: str,
    year: int | None,
    kind: str | None,
    user_level: str,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    *,
    title_id: int | None = None,
) -> DifficultyReport | None:
    with uow_factory() as uow:
        title = uow.titles.get(title_id) if title_id is not None else find_title(uow.titles.list_all(), name, year, kind)
        if title is None or title.id is None:
            return None
        episodes = uow.episodes.list_for_title(title.id)
        stats = [item for episode in episodes if episode.id and (item := uow.stats.get(episode.id)) is not None]
        has_cards = any(episode.id and uow.cards.count_for_episode(episode.id) for episode in episodes)
        records = uow.reviews.lemma_records()
    if not stats:
        return None
    return build_report(title, stats, known_words(user_level, records), has_cards=bool(has_cards))


def words_above_level(
    title_id: int, user_level: str, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork
) -> list[tuple[str, str, int]]:
    with uow_factory() as uow:
        episodes = uow.episodes.list_for_title(title_id)
        stats = [item for episode in episodes if episode.id and (item := uow.stats.get(episode.id)) is not None]
        records = uow.reviews.lemma_records()
    known = known_words(user_level, records)
    counts: Counter[str] = Counter()
    levels: dict[str, str | None] = {}
    for item in stats:
        counts.update(item.lemma_counts)
        levels.update(item.lemma_levels)
    limit = CEFR_LEVELS.index(known.user_level)
    return [
        (lemma, level, count)
        for lemma, count in counts.most_common()
        if (level := levels.get(lemma)) is not None
        and CEFR_LEVELS.index(level) > limit
        and not known.knows(lemma, level)
    ]
