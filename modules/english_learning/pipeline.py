from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.logger import get_logger
from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning import ai_expressions, cefr, lexicon
from modules.english_learning.analysis import Analysis, analyze_cues
from modules.english_learning.card_generation import GenerationProgress, generate_cards
from modules.english_learning.domain import (
    STORED_LEVELS,
    AiExpression,
    Episode,
    EpisodeWord,
    Example,
    SubtitleCue,
    Title,
    WordCandidate,
)
from modules.english_learning.expressions import LexiconMatcher
from modules.english_learning.language_filter import LanguageDetector, classify_cues
from modules.english_learning.lemmatizer import Lemmatizer, get_lemmatizer
from modules.english_learning.srt_parser import parse_srt
from modules.english_learning.stats import compute_stats
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

UowFactory = Callable[[], EnglishUnitOfWork]


@dataclass
class PipelineDeps:
    lemmatizer: Lemmatizer | None = None
    detector: LanguageDetector | None = None
    ensure_cefr: Callable[[], int] | None = None
    lexicon_loader: Callable[[UowFactory], LexiconMatcher | None] = lexicon.load_matcher
    find_expressions: Callable[..., Awaitable[list[AiExpression]]] = ai_expressions.find_expressions
    generate: Callable[..., Awaitable[GenerationProgress]] = generate_cards


@dataclass(frozen=True)
class RebuildResult:
    words: dict[int, list[EpisodeWord]]
    archived: int
    restored: int


@dataclass(frozen=True)
class Unit:
    title: Title
    episodes: list[Episode] = field(default_factory=list)

    @property
    def is_movie(self) -> bool:
        return self.title.kind == "movie"


def load_unit(uow: EnglishUnitOfWork, episode_id: int) -> Unit:
    episode = uow.episodes.get(episode_id)
    if episode is None:
        raise LookupError(f"Эпизод {episode_id} не найден")
    title = uow.titles.get(episode.title_id)
    if title is None:
        raise LookupError(f"Тайтл {episode.title_id} не найден")
    if title.kind == "movie" and title.id is not None:
        return Unit(title=title, episodes=uow.episodes.list_for_title(title.id))
    return Unit(title=title, episodes=[episode])


def load_cues(episode: Episode) -> list[SubtitleCue]:
    if not episode.srt_path or not Path(episode.srt_path).is_file():
        raise LookupError("Файл субтитров эпизода не найден — импортируйте серию заново")
    return parse_srt(Path(episode.srt_path).read_text(encoding="utf-8"))


def owner_of(episodes: Sequence[Episode], ms: int) -> Episode:
    if len(episodes) == 1:
        return episodes[0]
    for episode in episodes:
        start = episode.start_ms or 0
        end = episode.end_ms
        if start <= ms and (end is None or ms < end):
            return episode
    return episodes[-1] if ms >= (episodes[-1].start_ms or 0) else episodes[0]


def _cues_of(cues: Sequence[SubtitleCue], episodes: Sequence[Episode], episode: Episode) -> list[SubtitleCue]:
    if len(episodes) == 1:
        return list(cues)
    return [cue for cue in cues if owner_of(episodes, cue.start_ms).id == episode.id]


def _localize(candidate: WordCandidate, episode_id: int, episodes: Sequence[Episode]) -> EpisodeWord:
    own: list[Example] = [example for example in candidate.examples if owner_of(episodes, example.timestamp_ms).id == episode_id]
    examples = own or list(candidate.examples)
    first = examples[0] if examples else None
    return EpisodeWord(
        episode_id=episode_id,
        lemma=candidate.lemma,
        pos=candidate.pos,
        cefr=candidate.cefr,
        category=candidate.category,
        count=candidate.count,
        example=candidate.example if first is None or len(episodes) == 1 else first.text,
        timestamp_ms=candidate.timestamp_ms if first is None or len(episodes) == 1 else first.timestamp_ms,
        surface=candidate.surface,
        kind=candidate.kind,
        examples=examples,
        cefr_source=candidate.cefr_source,
        confidence=candidate.confidence,
        details=candidate.details,
    )


def _first_seen(candidate: WordCandidate) -> int:
    return min((example.timestamp_ms for example in candidate.examples), default=candidate.timestamp_ms)


def analyze_unit(
    unit: Unit,
    cues: Sequence[SubtitleCue],
    ai_items: Sequence[AiExpression],
    *,
    uow_factory: UowFactory,
    deps: PipelineDeps,
) -> Analysis:
    if deps.ensure_cefr is None:
        cefr.ensure_loaded(uow_factory)
    else:
        deps.ensure_cefr()
    return analyze_cues(
        cues,
        deps.lemmatizer or get_lemmatizer(),
        cefr.load_lookup(uow_factory),
        detector=deps.detector,
        lexicon=deps.lexicon_loader(uow_factory),
        ai_expressions=ai_items,
        target_levels=STORED_LEVELS,
    )


def rebuild(
    episode_id: int,
    *,
    uow_factory: UowFactory = EnglishUnitOfWork,
    deps: PipelineDeps | None = None,
    cues: Sequence[SubtitleCue] | None = None,
) -> RebuildResult:
    deps = deps or PipelineDeps()
    with uow_factory() as uow:
        unit = load_unit(uow, episode_id)
        ai_items = [item for episode in unit.episodes if episode.id for item in uow.ai_expressions.list_for_episode(episode.id)]
    source_cues = list(cues) if cues is not None else load_cues(unit.episodes[0])
    analysis = analyze_unit(unit, source_cues, ai_items, uow_factory=uow_factory, deps=deps)
    lookup = cefr.load_lookup(uow_factory)

    by_episode: dict[int, list[EpisodeWord]] = {episode.id: [] for episode in unit.episodes if episode.id is not None}
    for candidate in analysis.candidates:
        owner = owner_of(unit.episodes, _first_seen(candidate))
        if owner.id is not None:
            by_episode[owner.id].append(_localize(candidate, owner.id, unit.episodes))

    positions = {cue.index: position for position, cue in enumerate(source_cues)}
    archived = restored = 0
    with uow_factory() as uow:
        for episode in unit.episodes:
            if episode.id is None:
                continue
            words = by_episode[episode.id]
            uow.words.replace_for_episode(episode.id, words)
            part_cues = _cues_of(source_cues, unit.episodes, episode)
            indices = [positions[cue.index] for cue in part_cues]
            uow.stats.save(
                episode.id,
                compute_stats(
                    part_cues,
                    [analysis.analyzed[i] for i in indices],
                    [analysis.languages.labels[i] for i in indices],
                    lookup,
                    [hit for hit in analysis.expressions.hits if hit.cue_index in {cue.index for cue in part_cues}],
                ),
            )
            keys = {(word.lemma, word.pos) for word in words}
            cards = uow.cards.list_for_episode(episode.id, include_archived=True)
            to_archive = [card.id for card in cards if not card.archived and (card.lemma, card.pos) not in keys and card.id]
            to_restore = [card.id for card in cards if card.archived and (card.lemma, card.pos) in keys and card.id]
            archived += uow.cards.set_archived(to_archive, True)
            restored += uow.cards.set_archived(to_restore, False)
        uow.commit()
    logger.info(
        "Rebuilt %s: %d candidates, %d cards archived, %d restored",
        unit.title.name,
        sum(len(words) for words in by_episode.values()),
        archived,
        restored,
    )
    return RebuildResult(words=by_episode, archived=archived, restored=restored)


async def run_ai_layer(
    episode_id: int,
    *,
    uow_factory: UowFactory = EnglishUnitOfWork,
    deps: PipelineDeps | None = None,
    on_progress: Callable[[GenerationProgress], None] | None = None,
    force: bool = False,
) -> bool:
    deps = deps or PipelineDeps()
    with uow_factory() as uow:
        unit = load_unit(uow, episode_id)
        done = all(episode.id is not None and uow.ai_expressions.has_run(episode.id) for episode in unit.episodes)
    if done and not force:
        return False
    cues = load_cues(unit.episodes[0])
    languages = classify_cues(cues, deps.detector)

    def progress(done_chunks: int, total_chunks: int) -> None:
        if on_progress is not None:
            on_progress(GenerationProgress(done_chunks, total_chunks, 0, 0, phase="expressions"))

    try:
        found = await deps.find_expressions(cues, languages=languages.labels, on_chunk=progress)
    except AllProvidersFailed:
        logger.warning("AI expression pass skipped for episode %d: no provider answered", episode_id, exc_info=True)
        return False
    by_start = {cue.index: cue.start_ms for cue in cues}
    with uow_factory() as uow:
        for episode in unit.episodes:
            if episode.id is None:
                continue
            own = [item for item in found if owner_of(unit.episodes, by_start.get(item.cue_index, 0)).id == episode.id]
            uow.ai_expressions.replace_for_episode(episode.id, own)
            uow.ai_expressions.mark_run(episode.id)
        uow.commit()
    rebuild(episode_id, uow_factory=uow_factory, deps=deps, cues=cues)
    return True


async def process_episode(
    episode_id: int,
    *,
    uow_factory: UowFactory = EnglishUnitOfWork,
    deps: PipelineDeps | None = None,
    on_progress: Callable[[GenerationProgress], None] | None = None,
) -> GenerationProgress:
    deps = deps or PipelineDeps()
    try:
        await run_ai_layer(episode_id, uow_factory=uow_factory, deps=deps, on_progress=on_progress)
    except LookupError:
        logger.warning("AI expression pass skipped for episode %d: subtitles are missing", episode_id)

    def cards_progress(progress: GenerationProgress) -> None:
        if on_progress is not None:
            on_progress(replace(progress, phase="cards"))

    return await deps.generate(episode_id, uow_factory=uow_factory, on_progress=cards_progress)


@dataclass(frozen=True)
class ReanalyzeSummary:
    episodes: int
    archived: int
    restored: int
    failed: list[str]


def rebuild_all(uow_factory: UowFactory = EnglishUnitOfWork, deps: PipelineDeps | None = None) -> ReanalyzeSummary:
    with uow_factory() as uow:
        episodes = uow.episodes.list_all()
        titles = {title.id: title for title in uow.titles.list_all()}
    done_movies: set[int] = set()
    count = archived = restored = 0
    failed: list[str] = []
    for episode in episodes:
        title = titles.get(episode.title_id)
        if episode.id is None or title is None:
            continue
        if title.kind == "movie":
            if episode.title_id in done_movies:
                continue
            done_movies.add(episode.title_id)
        try:
            result = rebuild(episode.id, uow_factory=uow_factory, deps=deps)
        except LookupError as exc:
            failed.append(f"{title.name} {episode.code}: {exc}")
            continue
        count += len(result.words)
        archived += result.archived
        restored += result.restored
    return ReanalyzeSummary(episodes=count, archived=archived, restored=restored, failed=failed)
