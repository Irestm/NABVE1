from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from modules.ai_bridge.providers.base import AIResult, AllProvidersFailed
from modules.english_learning import card_generation, cefr, service_layer
from modules.english_learning.card_generation import GenerationProgress, clean_translations, generate_cards
from modules.english_learning.domain import Episode
from modules.english_learning.jobs import CardJobRegistry
from modules.english_learning.service_layer import folder_name, words_label
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer
from tests.modules.english_learning.test_service_layer import SRT

TRANSLATIONS = {"figure": ["понять", "разобраться"], "decide": ["решить"], "honest": ["честный", "искренний"]}


def _episode_id(uow_factory: Callable[[], EnglishUnitOfWork]) -> int:
    result = service_layer.import_srt_file(
        series_title="Breaking Bad",
        season=1,
        episode=1,
        raw=SRT,
        lemmatizer=FakeLemmatizer(),
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )
    assert result.episode.id is not None
    return result.episode.id


class _FakeModel:
    def __init__(self, *, skip: set[str] | None = None, broken_first: bool = False) -> None:
        self.skip = skip or set()
        self.broken_first = broken_first
        self.prompts: list[str] = []

    async def __call__(self, messages: Any, schema: Any, max_tokens: int) -> AIResult:
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if self.broken_first and len(self.prompts) == 1:
            return AIResult(text="{}", provider_name="fake", parsed_json={"cards": "oops"})
        cards = [
            {"lemma": lemma, "word": lemma, "translations_ru": values, "definition_en": f"To {lemma} something."}
            for lemma, values in TRANSLATIONS.items()
            if f"lemma: {lemma} " in prompt and lemma not in self.skip
        ]
        return AIResult(text="{}", provider_name="fake", parsed_json={"cards": cards})


def test_generates_cards_with_real_example_and_timestamp(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)
    seen: list[GenerationProgress] = []

    progress = asyncio.run(generate_cards(episode_id, complete=_FakeModel(), uow_factory=uow_factory, on_progress=seen.append))

    cards = service_layer.episode_cards(episode_id, uow_factory)
    assert progress.created == 3 and progress.total == 3
    assert seen[0].done == 0 and seen[-1].done == 3
    figure = next(card for card in cards if card.lemma == "figure")
    assert figure.translations_ru == ["понять", "разобраться"]
    assert figure.example == "I figured it out, John."
    assert figure.timestamp_ms == 1000
    assert figure.cefr == "B1"


def test_generation_is_idempotent(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)
    model = _FakeModel()

    asyncio.run(generate_cards(episode_id, complete=model, uow_factory=uow_factory))
    second = asyncio.run(generate_cards(episode_id, complete=model, uow_factory=uow_factory))

    assert second.total == 0
    assert len(service_layer.episode_cards(episode_id, uow_factory)) == 3


def test_invalid_batch_is_retried_once(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)
    model = _FakeModel(broken_first=True)

    progress = asyncio.run(generate_cards(episode_id, complete=model, uow_factory=uow_factory))

    assert progress.created == 3
    assert len(model.prompts) == 2


def test_words_without_a_valid_card_are_skipped(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)

    progress = asyncio.run(generate_cards(episode_id, complete=_FakeModel(skip={"honest"}), uow_factory=uow_factory))

    assert (progress.created, progress.skipped) == (2, 1)


def test_batches_are_split(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)
    model = _FakeModel()

    asyncio.run(generate_cards(episode_id, complete=model, uow_factory=uow_factory, batch_size=2))

    assert len(model.prompts) == 2


def test_provider_outage_propagates(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id = _episode_id(uow_factory)

    async def down(*args: Any) -> AIResult:
        raise AllProvidersFailed([("ollama", "down")])

    with pytest.raises(AllProvidersFailed):
        asyncio.run(generate_cards(episode_id, complete=down, uow_factory=uow_factory))


def test_unknown_episode(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    with pytest.raises(LookupError):
        asyncio.run(generate_cards(404, complete=_FakeModel(), uow_factory=uow_factory))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["понять.", " понять ", "figure", "разобраться", "осознать", "уяснить"], ["понять", "разобраться", "осознать"]),
        ("не список", []),
        ([1, None, "ЧЕСТНЫЙ"], ["ЧЕСТНЫЙ"]),
    ],
)
def test_clean_translations(raw: Any, expected: list[str]) -> None:
    assert clean_translations(raw) == expected


def test_cards_from_reply_ignores_unknown_and_duplicate_lemmas() -> None:
    from modules.english_learning.domain import EpisodeWord

    words = [EpisodeWord(1, "decide", "VERB", "A2", "core", 1, "We decided.", 5, "decided")]
    parsed = {
        "cards": [
            {"lemma": "unknown", "word": "x", "translations_ru": ["икс"], "definition_en": "x"},
            {"lemma": "Decide", "word": "decide", "translations_ru": ["решить"], "definition_en": "Choose."},
            {"lemma": "decide", "word": "decide", "translations_ru": ["решать"], "definition_en": "Again."},
        ]
    }

    cards = card_generation.cards_from_reply(words, parsed)

    assert [(card.lemma, card.translations_ru) for card in cards] == [("decide", ["решить"])]


@pytest.mark.parametrize(
    ("count", "label"),
    [(1, "1 слово"), (2, "2 слова"), (5, "5 слов"), (11, "11 слов"), (21, "21 слово"), (104, "104 слова"), (112, "112 слов")],
)
def test_words_label(count: int, label: str) -> None:
    assert words_label(count) == label


def test_folder_name() -> None:
    episode = Episode(title_id=1, season=1, episode=1, source="manual")

    assert folder_name("Breaking Bad", episode, 42) == "Breaking Bad — S01E01 — 42 слова"


def test_job_registry_tracks_progress_and_dedupes() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()

        async def generator(episode_id: int, *, on_progress: Any) -> GenerationProgress:
            on_progress(GenerationProgress(1, 4, 1, 0))
            await gate.wait()
            return GenerationProgress(4, 4, 4, 0)

        registry = CardJobRegistry(generator)
        job = registry.start(7)
        await asyncio.sleep(0)
        assert registry.start(7).id == job.id
        running = registry.get(job.id)
        assert running is not None and (running.state, running.done, running.total) == ("running", 1, 4)
        gate.set()
        finished = await asyncio.wait_for(registry.wait(job.id), timeout=5)
        assert finished is not None and finished.state == "done"
        assert registry.start(7).id != job.id

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_job_registry_records_failures() -> None:
    async def scenario() -> None:
        async def generator(episode_id: int, *, on_progress: Any) -> GenerationProgress:
            raise AllProvidersFailed([("ollama", "down")])

        registry = CardJobRegistry(generator)
        job = registry.start(1)
        finished = await asyncio.wait_for(registry.wait(job.id), timeout=5)
        assert finished is not None and finished.state == "failed" and "ollama" in (finished.error or "")

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))
