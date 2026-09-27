from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import pytest

from modules.ai_bridge.providers.base import AIResult
from modules.english_learning import cefr, lexicon, pipeline, service_layer
from modules.english_learning.ai_expressions import chunk_cues, find_expressions, validate_reply
from modules.english_learning.card_generation import generate_cards
from modules.english_learning.domain import AiExpression, LexiconEntry, ReviewEntry, SubtitleCue
from modules.english_learning.expressions import LexiconMatcher, merge_hits, scan_expressions
from modules.english_learning.lemmatizer import AnalyzedToken, SpacyLemmatizer
from modules.english_learning.uow import EnglishUnitOfWork

IDIOM_SRT = """1
00:00:01,000 --> 00:00:03,000
Break a leg tonight, kid.

2
00:00:04,000 --> 00:00:06,000
I will never give up on you.

3
00:00:07,000 --> 00:00:09,000
We need to figure it out before noon.

4
00:00:10,000 --> 00:00:12,000
Let's wrap up the meeting now.

5
00:00:13,000 --> 00:00:15,000
Hey, what's up with you today?

6
00:00:16,000 --> 00:00:18,000
She wants to run a company one day.

7
00:00:19,000 --> 00:00:21,000
Run home before the storm comes.

8
00:00:22,000 --> 00:00:24,000
They decided that the consequence was fair.
"""

CEFR_CSV = """headword,pos,CEFR
break,verb,A1
leg,noun,A1
run,verb,A1
company,noun,A2
give,verb,A1
figure,verb,B1
wrap,verb,B1
meeting,noun,A2
storm,noun,A2
decide,verb,A2
fair,adjective,B1
consequence,noun,C1
tonight,adverb,A1
kid,noun,A2
noon,noun,A2
today,adverb,A1
"""

LEXICON = [
    LexiconEntry("break a leg", "break a leg", "idiom", None, "test"),
    LexiconEntry("what's up", "what's up", "slang", "A2", "test"),
    LexiconEntry("lose one's temper", "lose one's temper", "idiom", "B2", "test"),
]


@pytest.fixture(scope="module")
def spacy_lemmatizer() -> SpacyLemmatizer:
    lemmatizer = SpacyLemmatizer()
    try:
        list(lemmatizer.analyze(["warm up"]))
    except Exception as exc:
        pytest.skip(f"spaCy model unavailable: {exc}")
    return lemmatizer


def _import(uow_factory: Callable[[], EnglishUnitOfWork], lemmatizer: SpacyLemmatizer) -> service_layer.ImportResult:
    return service_layer.import_subtitles(
        series_title="Stage",
        season=1,
        episode=1,
        srt_text=IDIOM_SRT,
        source="manual",
        lemmatizer=lemmatizer,
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )


def test_expressions_are_found_normalized_and_absorb_their_words(
    uow_factory: Callable[[], EnglishUnitOfWork], spacy_lemmatizer: SpacyLemmatizer
) -> None:
    lexicon.store(LEXICON, uow_factory)

    result = _import(uow_factory, spacy_lemmatizer)

    expressions = {word.lemma: word for word in result.words if word.is_expression}
    assert {"break a leg", "give up", "figure out", "wrap up", "what's up"} <= set(expressions)
    assert expressions["break a leg"].kind == "idiom"
    assert expressions["give up"].kind == "phrasal_verb"
    assert expressions["figure out"].surface == "figure it out"
    assert expressions["what's up"].cefr == "A2" and expressions["what's up"].cefr_source == "lexicon"
    single = {word.lemma for word in result.words if not word.is_expression}
    assert "break" not in single and "leg" not in single
    assert "give" not in single and "wrap" not in single and "figure" not in single
    assert "run" in single
    run = next(word for word in result.words if word.lemma == "run")
    assert {example.text for example in run.examples} == {
        "She wants to run a company one day.",
        "Run home before the storm comes.",
    }


def test_c_levels_are_not_stored_but_counted_in_stats(
    uow_factory: Callable[[], EnglishUnitOfWork], spacy_lemmatizer: SpacyLemmatizer
) -> None:
    result = _import(uow_factory, spacy_lemmatizer)

    assert "consequence" not in {word.lemma for word in result.words}
    assert {word.cefr for word in result.words if not word.is_expression} <= {"A1", "A2", "B1", "B2", None}
    with uow_factory() as uow:
        stats = uow.stats.get(result.episode.id or 0)
    assert stats is not None
    assert stats.tokens_by_level["C1"] == 1
    assert ("consequence", 1) in stats.top_above_b2
    assert stats.words_per_minute > 0
    assert stats.non_english_share == 0.0


class _SenseModel:
    async def __call__(self, messages: Any, schema: Any, max_tokens: int) -> AIResult:
        prompt = messages[-1]["content"]
        cards: list[dict[str, Any]] = []
        for line in prompt.splitlines():
            if not line.startswith("- lemma: "):
                continue
            lemma = line.removeprefix("- lemma: ").split(" | ")[0]
            if lemma == "run":
                cards.append(_card("run", ["управлять"], "управлять", 1))
                cards.append(_card("run", ["бежать"], "бежать", 2))
            else:
                cards.append(_card(lemma, ["перевод"], None, 1))
        return AIResult(text="{}", provider_name="fake", parsed_json={"cards": cards})


def _card(lemma: str, translations: list[str], label: str | None, example: int) -> dict[str, Any]:
    return {
        "lemma": lemma,
        "word": lemma,
        "sense_label": label,
        "translations_ru": translations,
        "definition_en": "Something.",
        "literal_translation": None,
        "example_index": example,
    }


def test_run_gets_two_cards_with_context_senses(
    uow_factory: Callable[[], EnglishUnitOfWork], spacy_lemmatizer: SpacyLemmatizer
) -> None:
    result = _import(uow_factory, spacy_lemmatizer)
    episode_id = result.episode.id or 0

    asyncio.run(generate_cards(episode_id, complete=_SenseModel(), uow_factory=uow_factory))

    runs = [card for card in service_layer.episode_cards(episode_id, uow_factory) if card.lemma == "run"]
    assert sorted((card.sense_label, card.example) for card in runs) == [
        ("бежать", "Run home before the storm comes."),
        ("управлять", "She wants to run a company one day."),
    ]


def test_hallucinated_ai_expression_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    chunk = [SubtitleCue(1, 0, 1000, "I will never give up on you.")]
    parsed = {
        "expressions": [
            {
                "surface_form": "give up",
                "normalized": "give up",
                "line_index": 1,
                "kind": "phrasal_verb",
                "meaning_en": "To stop trying.",
                "translation_ru": ["сдаваться"],
                "literal_translation": None,
                "cefr_estimate": "B1",
                "confidence": 0.9,
            },
            {
                "surface_form": "piece of cake",
                "normalized": "piece of cake",
                "line_index": 1,
                "kind": "idiom",
                "meaning_en": "Easy.",
                "translation_ru": ["проще простого"],
                "literal_translation": "кусок торта",
                "cefr_estimate": "B1",
                "confidence": 0.95,
            },
            {
                "surface_form": "on you",
                "normalized": "on you",
                "line_index": 1,
                "kind": "collocation",
                "meaning_en": "x",
                "translation_ru": ["на тебя"],
                "literal_translation": None,
                "cefr_estimate": None,
                "confidence": 0.4,
            },
        ]
    }

    with caplog.at_level(logging.WARNING):
        accepted = validate_reply(parsed, chunk)

    assert [item.normalized for item in accepted] == ["give up"]
    assert "piece of cake" in caplog.text


def test_chunks_have_overlap() -> None:
    cues = [SubtitleCue(i, i * 1000, i * 1000 + 500, f"line {i}") for i in range(1, 101)]

    chunks = chunk_cues(cues)

    assert [(chunk[0].index, chunk[-1].index) for chunk in chunks] == [(1, 40), (36, 75), (71, 100)]


def test_find_expressions_dedupes_overlapping_chunks() -> None:
    cues = [SubtitleCue(i, i * 1000, i * 1000 + 500, "Let's wrap up now." if i == 38 else f"plain {i}") for i in range(1, 60)]

    async def model(messages: Any, schema: Any, max_tokens: int) -> AIResult:
        items = []
        if "[38] Let's wrap up now." in messages[-1]["content"]:
            items.append(
                {
                    "surface_form": "wrap up",
                    "normalized": "wrap up",
                    "line_index": 38,
                    "kind": "phrasal_verb",
                    "meaning_en": "To finish.",
                    "translation_ru": ["заканчивать"],
                    "literal_translation": None,
                    "cefr_estimate": "B1",
                    "confidence": 0.8,
                }
            )
        return AIResult(text="{}", provider_name="fake", parsed_json={"expressions": items})

    found = asyncio.run(find_expressions(cues, complete=model))

    assert [(item.normalized, item.cue_index) for item in found] == [("wrap up", 38)]


def _tokens(*words: tuple[str, str, str]) -> list[AnalyzedToken]:
    return [AnalyzedToken(text, lemma, pos, False, text.isalpha(), False, False) for text, lemma, pos in words]


def test_lexicon_matches_inflections_and_placeholders() -> None:
    matcher = LexiconMatcher(LEXICON)
    cue = SubtitleCue(1, 0, 1000, "He broke a leg and lost his temper.")
    tokens = _tokens(
        ("He", "he", "PRON"),
        ("broke", "break", "VERB"),
        ("a", "a", "DET"),
        ("leg", "leg", "NOUN"),
        ("and", "and", "CCONJ"),
        ("lost", "lose", "VERB"),
        ("his", "his", "PRON"),
        ("temper", "temper", "NOUN"),
    )

    hits = matcher.find(cue, tokens)

    assert {(hit.normalized, hit.surface_form, hit.token_indices) for hit in hits} == {
        ("break a leg", "broke a leg", (1, 2, 3)),
        ("lose one's temper", "lost his temper", (5, 7)),
    }


def test_merge_prefers_lexicon_level_over_ai_estimate() -> None:
    cue = SubtitleCue(1, 0, 1000, "Hey, what's up?")
    tokens = _tokens(("Hey", "hey", "INTJ"), ("what", "what", "PRON"), ("'s", "be", "AUX"), ("up", "up", "ADP"))
    ai_item = AiExpression(1, "what's up", "what's up", "slang", "Hello.", ["как дела"], None, "B1", 0.9)

    scan = scan_expressions([cue], [tokens], lexicon=LexiconMatcher(LEXICON), ai_expressions=[ai_item])

    (candidate,) = scan.candidates
    assert (candidate.cefr, candidate.cefr_source, candidate.kind) == ("A2", "lexicon", "slang")
    assert candidate.details is not None and candidate.details["translations_ru"] == ["как дела"]
    assert merge_hits([], {}) == []


def test_reanalyze_archives_absorbed_cards_and_keeps_review_log(
    uow_factory: Callable[[], EnglishUnitOfWork], spacy_lemmatizer: SpacyLemmatizer
) -> None:
    result = _import(uow_factory, spacy_lemmatizer)
    episode_id = result.episode.id or 0
    asyncio.run(generate_cards(episode_id, complete=_SenseModel(), uow_factory=uow_factory))
    cards = {card.lemma: card for card in service_layer.episode_cards(episode_id, uow_factory)}
    assert "break" in cards and "leg" in cards
    decide = cards["decide"]
    with uow_factory() as uow:
        uow.reviews.add(ReviewEntry(card_id=decide.id or 0, mode="input", correct=True, answer="решить"))
        uow.commit()

    lexicon.store(LEXICON, uow_factory)
    outcome = pipeline.rebuild(
        episode_id,
        uow_factory=uow_factory,
        deps=pipeline.PipelineDeps(
            lemmatizer=spacy_lemmatizer, ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV)
        ),
    )

    active = {card.lemma for card in service_layer.episode_cards(episode_id, uow_factory)}
    assert "break" not in active and "leg" not in active
    assert outcome.archived == 2
    with uow_factory() as uow:
        archived = [card for card in uow.cards.list_for_episode(episode_id, include_archived=True) if card.archived]
        assert {card.lemma for card in archived} == {"break", "leg"}
        kept = uow.cards.get(decide.id or 0)
        assert kept is not None and not kept.archived
        assert uow.reviews.count_for_card(decide.id or 0) == 1
    assert "break a leg" in {word.lemma for word in outcome.words[episode_id]}


def test_ai_layer_in_background_adds_expressions(
    uow_factory: Callable[[], EnglishUnitOfWork], spacy_lemmatizer: SpacyLemmatizer
) -> None:
    result = _import(uow_factory, spacy_lemmatizer)
    episode_id = result.episode.id or 0
    calls: list[str] = []

    async def fake_find(cues: Any, **kwargs: Any) -> list[AiExpression]:
        calls.append("ai")
        return [AiExpression(6, "run a company", "run a company", "collocation", "Manage.", ["управлять компанией"], None, "B1", 0.9)]

    deps = pipeline.PipelineDeps(
        lemmatizer=spacy_lemmatizer,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
        find_expressions=fake_find,
    )
    assert asyncio.run(pipeline.run_ai_layer(episode_id, uow_factory=uow_factory, deps=deps)) is True
    assert asyncio.run(pipeline.run_ai_layer(episode_id, uow_factory=uow_factory, deps=deps)) is False

    words = {word.lemma: word for word in service_layer.episode_words(episode_id, uow_factory)}
    assert words["run a company"].kind == "collocation"
    assert words["run a company"].details is not None
    assert words["run"].count == 1
    assert calls == ["ai"]
