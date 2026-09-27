from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
EpisodeSource = Literal["youtube", "opensubtitles", "manual", "ai_guess"]
WordCategory = Literal["core", "extra"]
ReviewMode = Literal["choice", "input"]
TitleKind = Literal["series", "movie"]
ItemKind = Literal["word", "phrasal_verb", "idiom", "collocation", "slang"]
CefrSource = Literal["list", "lexicon", "ai"]
MweMode = Literal["follow_levels", "always"]
FilterScope = Literal["global", "title", "episode"]

CEFR_LEVELS: tuple[CefrLevel, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
STORED_LEVELS: frozenset[str] = frozenset({"A1", "A2", "B1", "B2"})
ABOVE_STORED_LEVELS: frozenset[str] = frozenset({"C1", "C2"})
TARGET_LEVELS: frozenset[str] = STORED_LEVELS
EXPRESSION_KINDS: frozenset[str] = frozenset({"phrasal_verb", "idiom", "collocation", "slang"})
ITEM_KINDS: tuple[ItemKind, ...] = ("word", "phrasal_verb", "idiom", "collocation", "slang")
MWE_POS = "MWE"
DEFAULT_FILTER_LEVELS: tuple[str, ...] = ("A2", "B1", "B2")
DEFAULT_USER_LEVEL: CefrLevel = "B1"


def clock(ms: int) -> str:
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Example:
    text: str
    timestamp_ms: int
    cue_index: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "timestamp_ms": self.timestamp_ms, "cue_index": self.cue_index}


@dataclass(frozen=True)
class WordCandidate:
    lemma: str
    pos: str
    cefr: str | None
    category: WordCategory
    count: int
    example: str
    timestamp_ms: int
    surface: str
    kind: ItemKind = "word"
    examples: tuple[Example, ...] = ()
    cefr_source: CefrSource | None = None
    confidence: float | None = None
    details: dict[str, Any] | None = None


@dataclass
class Title:
    name: str
    kind: TitleKind = "series"
    year: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    id: int | None = None
    created_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.year})" if self.kind == "movie" and self.year else self.name


@dataclass
class Episode:
    title_id: int
    source: EpisodeSource
    season: int | None = None
    episode: int | None = None
    part: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    title: str | None = None
    srt_path: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    @property
    def is_series_episode(self) -> bool:
        return self.season is not None and self.episode is not None

    @property
    def code(self) -> str:
        if self.season is not None and self.episode is not None:
            return f"S{self.season:02d}E{self.episode:02d}"
        if self.part is not None:
            span = f" · {clock(self.start_ms or 0)}–{clock(self.end_ms or 0)}" if self.end_ms is not None else ""
            return f"Часть {self.part}{span}"
        return "Фильм"


@dataclass
class EpisodeWord:
    episode_id: int
    lemma: str
    pos: str
    cefr: str | None
    category: WordCategory
    count: int
    example: str
    timestamp_ms: int
    surface: str
    kind: ItemKind = "word"
    examples: list[Example] = field(default_factory=list)
    cefr_source: CefrSource | None = None
    confidence: float | None = None
    details: dict[str, Any] | None = None
    id: int | None = None

    @property
    def is_expression(self) -> bool:
        return self.kind != "word"


@dataclass
class Card:
    episode_id: int
    word: str
    lemma: str
    pos: str
    cefr: str | None
    translations_ru: list[str]
    definition_en: str
    example: str
    timestamp_ms: int
    category: WordCategory
    kind: ItemKind = "word"
    surface_form: str | None = None
    sense_label: str | None = None
    literal_translation: str | None = None
    cefr_source: CefrSource | None = None
    confidence: float | None = None
    archived: bool = False
    id: int | None = None

    @property
    def is_expression(self) -> bool:
        return self.kind != "word"


@dataclass(frozen=True)
class AiExpression:
    cue_index: int
    surface_form: str
    normalized: str
    kind: ItemKind
    meaning_en: str
    translations_ru: list[str]
    literal_translation: str | None
    cefr_estimate: str | None
    confidence: float


@dataclass(frozen=True)
class LexiconEntry:
    expression: str
    normalized: str
    kind: ItemKind
    cefr: str | None
    source: str


@dataclass(frozen=True)
class EpisodeStats:
    token_count: int
    lemma_count: int
    tokens_by_level: dict[str, int]
    lemmas_by_level: dict[str, int]
    expressions_per_1000: float
    words_per_minute: float
    non_english_share: float
    off_list_share: float
    top_above_b2: list[tuple[str, int]]
    lemma_counts: dict[str, int]
    lemma_levels: dict[str, str | None]
    cue_count: int
    non_english_cues: int
    speech_minutes: float
    slang_count: int = 0
    idiom_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "token_count": self.token_count,
            "lemma_count": self.lemma_count,
            "tokens_by_level": self.tokens_by_level,
            "lemmas_by_level": self.lemmas_by_level,
            "expressions_per_1000": self.expressions_per_1000,
            "words_per_minute": self.words_per_minute,
            "non_english_share": self.non_english_share,
            "off_list_share": self.off_list_share,
            "top_above_b2": [list(item) for item in self.top_above_b2],
            "lemma_counts": self.lemma_counts,
            "lemma_levels": self.lemma_levels,
            "cue_count": self.cue_count,
            "non_english_cues": self.non_english_cues,
            "speech_minutes": self.speech_minutes,
            "slang_count": self.slang_count,
            "idiom_count": self.idiom_count,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "EpisodeStats":
        return EpisodeStats(
            token_count=int(data.get("token_count", 0)),
            lemma_count=int(data.get("lemma_count", 0)),
            tokens_by_level={str(k): int(v) for k, v in dict(data.get("tokens_by_level", {})).items()},
            lemmas_by_level={str(k): int(v) for k, v in dict(data.get("lemmas_by_level", {})).items()},
            expressions_per_1000=float(data.get("expressions_per_1000", 0.0)),
            words_per_minute=float(data.get("words_per_minute", 0.0)),
            non_english_share=float(data.get("non_english_share", 0.0)),
            off_list_share=float(data.get("off_list_share", 0.0)),
            top_above_b2=[(str(item[0]), int(item[1])) for item in data.get("top_above_b2", [])],
            lemma_counts={str(k): int(v) for k, v in dict(data.get("lemma_counts", {})).items()},
            lemma_levels={str(k): (str(v) if v else None) for k, v in dict(data.get("lemma_levels", {})).items()},
            cue_count=int(data.get("cue_count", 0)),
            non_english_cues=int(data.get("non_english_cues", 0)),
            speech_minutes=float(data.get("speech_minutes", 0.0)),
            slang_count=int(data.get("slang_count", 0)),
            idiom_count=int(data.get("idiom_count", 0)),
        )


@dataclass(frozen=True)
class FilterSettings:
    levels: tuple[str, ...] = DEFAULT_FILTER_LEVELS
    include_unleveled: bool = False
    mwe_mode: MweMode = "always"

    def admits(self, kind: str, cefr: str | None) -> bool:
        if kind != "word" and self.mwe_mode == "always":
            return True
        if cefr is None:
            return self.include_unleveled
        return cefr in self.levels


@dataclass
class LearnSession:
    episode_id: int
    settings: dict[str, object] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    mistakes: int = 0
    id: int | None = None


@dataclass
class ReviewEntry:
    card_id: int
    mode: ReviewMode
    correct: bool
    answer: str
    session_id: int | None = None
    ts: datetime | None = None
    id: int | None = None
