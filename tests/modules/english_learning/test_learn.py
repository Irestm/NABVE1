from __future__ import annotations

from collections.abc import Callable

import pytest

from modules.english_learning import learn
from modules.english_learning.domain import Card, Episode, Series
from modules.english_learning.uow import EnglishUnitOfWork


def _seed(uow_factory: Callable[[], EnglishUnitOfWork], *, with_cards: bool = True) -> tuple[int, list[int]]:
    with uow_factory() as uow:
        series = Series(title="Dark")
        uow.series.add(series)
        assert series.id is not None
        episode = Episode(series_id=series.id, season=1, episode=1, source="manual")
        uow.episodes.add(episode)
        assert episode.id is not None
        ids: list[int] = []
        if with_cards:
            for word, translations in (("decide", ["решить", "решать"]), ("honest", ["честный"])):
                card = Card(episode.id, word, word, "VERB", "A2", translations, "Def.", f"I {word}.", 0, "core")
                ids.append(uow.cards.add(card))
        uow.commit()
        return episode.id, ids


def test_session_flow_logs_answers_and_summarizes_hard_words(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id, (decide, honest) = _seed(uow_factory)
    session = learn.start_session(episode_id, learn.LearnSettings(), uow_factory)
    assert session.id is not None

    wrong = learn.answer(session.id, decide, "choice", "честный", uow_factory=uow_factory)
    typo = learn.answer(session.id, decide, "input", "решитъ", uow_factory=uow_factory)
    learn.answer(session.id, honest, "input", "лживый", uow_factory=uow_factory)
    learn.answer(session.id, honest, "input", "лживый", uow_factory=uow_factory)
    summary = learn.finish(session.id, uow_factory)

    assert not wrong.result.correct and wrong.expected == ["решить", "решать"]
    assert typo.result.correct and not typo.result.exact
    assert summary.mistakes == 3
    assert [(item.card.word, item.mistakes) for item in summary.hard_words] == [("honest", 2), ("decide", 1)]
    assert summary.session.finished_at is not None


def test_ru_en_direction_expects_the_english_word(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id, (decide, _) = _seed(uow_factory)
    session = learn.start_session(episode_id, learn.LearnSettings(direction="ru_en"), uow_factory)
    assert session.id is not None

    outcome = learn.answer(session.id, decide, "input", "decided", lemmatize=lambda text: "decide", uow_factory=uow_factory)

    assert outcome.result.correct
    assert outcome.expected == ["decide"]


def test_start_session_validation(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    empty_episode, _ = _seed(uow_factory, with_cards=False)

    with pytest.raises(ValueError):
        learn.start_session(empty_episode, learn.LearnSettings(), uow_factory)
    with pytest.raises(LookupError):
        learn.start_session(999, learn.LearnSettings(), uow_factory)
    with pytest.raises(ValueError):
        learn.start_session(empty_episode, learn.LearnSettings(mode="speed"), uow_factory)


def test_answer_rejects_foreign_cards(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    episode_id, _ = _seed(uow_factory)
    other_episode, (foreign, _) = _seed(uow_factory)
    session = learn.start_session(episode_id, learn.LearnSettings(), uow_factory)
    assert session.id is not None and other_episode != episode_id

    with pytest.raises(LookupError):
        learn.answer(session.id, foreign, "input", "x", uow_factory=uow_factory)
    with pytest.raises(LookupError):
        learn.answer(12345, foreign, "input", "x", uow_factory=uow_factory)
