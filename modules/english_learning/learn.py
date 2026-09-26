from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from modules.english_learning.answer_check import CheckResult, Direction, check_answer
from modules.english_learning.domain import Card, LearnSession, ReviewEntry, ReviewMode
from modules.english_learning.lemmatizer import Lemmatizer, LemmatizerUnavailableError, get_lemmatizer
from modules.english_learning.uow import EnglishUnitOfWork

MODES: frozenset[str] = frozenset({"choice", "input", "mixed"})
DIRECTIONS: frozenset[str] = frozenset({"en_ru", "ru_en"})


@dataclass(frozen=True)
class LearnSettings:
    shuffle: bool = True
    direction: Direction = "en_ru"
    mode: str = "mixed"

    def as_dict(self) -> dict[str, Any]:
        return {"shuffle": self.shuffle, "direction": self.direction, "mode": self.mode}


@dataclass(frozen=True)
class AnswerOutcome:
    result: CheckResult
    expected: list[str]
    card: Card


@dataclass(frozen=True)
class HardWord:
    card: Card
    mistakes: int


@dataclass(frozen=True)
class SessionSummary:
    session: LearnSession
    mistakes: int
    hard_words: list[HardWord]


def expected_answers(card: Card, direction: Direction) -> list[str]:
    if direction == "en_ru":
        return list(card.translations_ru)
    return list(dict.fromkeys([card.word, card.lemma]))


def english_lemma_function(lemmatizer: Lemmatizer | None = None) -> Callable[[str], str]:
    def lemmatize(text: str) -> str:
        try:
            tokens = next(iter((lemmatizer or get_lemmatizer()).analyze([text])), [])
        except LemmatizerUnavailableError:
            return text
        return " ".join(token.lemma.lower() for token in tokens if token.is_alpha)

    return lemmatize


def start_session(
    episode_id: int, settings: LearnSettings, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork
) -> LearnSession:
    if settings.mode not in MODES or settings.direction not in DIRECTIONS:
        raise ValueError("Неизвестный режим или направление")
    with uow_factory() as uow:
        if uow.episodes.get(episode_id) is None:
            raise LookupError(f"Эпизод {episode_id} не найден")
        if uow.cards.count_for_episode(episode_id) == 0:
            raise ValueError("В эпизоде ещё нет карточек")
        session = LearnSession(episode_id=episode_id, settings=settings.as_dict())
        uow.sessions.add(session)
        uow.commit()
        return session


def answer(
    session_id: int,
    card_id: int,
    mode: ReviewMode,
    given: str,
    *,
    lemmatize: Callable[[str], str] | None = None,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
) -> AnswerOutcome:
    with uow_factory() as uow:
        session = uow.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Сессия {session_id} не найдена")
        card = uow.cards.get(card_id)
        if card is None or card.episode_id != session.episode_id:
            raise LookupError(f"Карточка {card_id} не из этой сессии")
        direction: Direction = "ru_en" if session.settings.get("direction") == "ru_en" else "en_ru"
        expected = expected_answers(card, direction)
        if mode == "choice":
            matched = given.strip() in expected
            result = CheckResult(correct=matched, exact=matched, matched=given.strip() if matched else None)
        else:
            result = check_answer(
                given,
                expected,
                direction,
                lemma=card.lemma,
                lemmatize=lemmatize or english_lemma_function(),
            )
        uow.reviews.add(
            ReviewEntry(card_id=card_id, session_id=session_id, mode=mode, correct=result.correct, answer=given)
        )
        uow.commit()
        return AnswerOutcome(result=result, expected=expected, card=card)


def finish(session_id: int, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> SessionSummary:
    with uow_factory() as uow:
        session = uow.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Сессия {session_id} не найдена")
        by_card = uow.reviews.mistakes_by_card(session_id)
        mistakes = sum(by_card.values())
        hard_words = [
            HardWord(card=card, mistakes=count)
            for card_id, count in by_card.items()
            if (card := uow.cards.get(card_id)) is not None
        ]
        uow.sessions.finish(session_id, mistakes)
        uow.commit()
        finished = uow.sessions.get(session_id) or session
        return SessionSummary(session=finished, mistakes=mistakes, hard_words=hard_words)
