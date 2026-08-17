from __future__ import annotations

import pytest

from modules.quizlet_clone import game_modes
from modules.quizlet_clone.game_modes import (
    FlashcardsSession,
    GameOverError,
    LearnSession,
    MatchSession,
    TestSession as QuizletTestSession,
    UnknownSessionError,
    VoiceSession,
)
from modules.quizlet_clone.models import GameMode, SetSource, StudySet, Term
from modules.quizlet_clone.storage import QuizletUnitOfWork


def _uow(tmp_path) -> QuizletUnitOfWork:
    return QuizletUnitOfWork(tmp_path / "assistant.db")


def _seed_terms(tmp_path, pairs: list[tuple[str, str]]) -> tuple[QuizletUnitOfWork, list[Term]]:
    uow = _uow(tmp_path)
    with uow:
        uow.sets.add(StudySet(id="s1", title="Set", source=SetSource.MANUAL))
        for position, (term_text, definition) in enumerate(pairs):
            uow.terms.add(Term(id=f"t{position}", set_id="s1", term=term_text, definition=definition, position=position))
        uow.commit()
        terms = uow.terms.list_by_set("s1")
    return uow, terms


def test_flashcards_flip_and_navigate(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1"), ("b", "2")])
    session = FlashcardsSession("sess", "s1", GameMode.FLASHCARDS, terms)

    state = session.state()
    assert state["index"] == 0 and state["flipped"] is False and state["term"] == "a"

    state = session.answer(uow, {"action": "flip"})
    assert state["flipped"] is True

    state = session.answer(uow, {"action": "next"})
    assert state["index"] == 1 and state["term"] == "b" and state["flipped"] is False

    # Past the end: index stays clamped, no error.
    state = session.answer(uow, {"action": "next"})
    assert state["index"] == 1


def test_learn_session_finishes_after_enough_correct_answers(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1")])
    session = LearnSession("sess", "s1", GameMode.LEARN, terms)

    assert session.state()["finished"] is False
    session.answer(uow, {"term_id": "t0", "known": True})
    state = session.answer(uow, {"term_id": "t0", "known": True})

    assert state["finished"] is True
    with uow:
        stored = uow.terms.get("t0")
    assert stored is not None and stored.times_correct == 2


def test_learn_session_wrong_answer_increases_remaining_need(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1")])
    session = LearnSession("sess", "s1", GameMode.LEARN, terms)

    session.answer(uow, {"term_id": "t0", "known": False})
    assert session.remaining_needed["t0"] == 3

    session.answer(uow, {"term_id": "t0", "known": True})
    session.answer(uow, {"term_id": "t0", "known": True})
    state = session.answer(uow, {"term_id": "t0", "known": True})
    assert state["finished"] is True


def test_learn_session_rejects_answer_for_wrong_term(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1")])
    session = LearnSession("sess", "s1", GameMode.LEARN, terms)

    with pytest.raises(ValueError):
        session.answer(uow, {"term_id": "does-not-exist", "known": True})


def test_voice_session_fuzzy_matches_close_answer_as_correct(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("gato", "домашняя кошка")])
    session = VoiceSession("sess", "s1", GameMode.VOICE, terms)

    result = session.answer_spoken(uow, "домашняя кошка")

    assert result["correct"] is True
    assert result["answered_term"] == "gato"
    with uow:
        stored = uow.terms.get("t0")
    assert stored is not None and stored.times_correct == 1


def test_voice_session_marks_unrelated_answer_as_incorrect(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("gato", "домашняя кошка")])
    session = VoiceSession("sess", "s1", GameMode.VOICE, terms)

    result = session.answer_spoken(uow, "совершенно другой текст про самолёты")

    assert result["correct"] is False
    with uow:
        stored = uow.terms.get("t0")
    assert stored is not None and stored.times_wrong == 1


def test_voice_session_raises_once_finished(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "первое определение")])
    session = VoiceSession("sess", "s1", GameMode.VOICE, terms)
    session.answer_spoken(uow, "первое определение")
    session.answer_spoken(uow, "первое определение")
    assert session.finished is True

    with pytest.raises(GameOverError):
        session.answer_spoken(uow, "ещё один ответ")


def test_match_session_correct_and_incorrect_pairs(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1"), ("b", "2")])
    session = MatchSession("sess", "s1", GameMode.MATCH, terms)

    term_tile_a = next(tid for tid, meta in session.tile_meta.items() if meta["pair_id"] == "t0" and meta["kind"] == "term")
    definition_tile_a = next(
        tid for tid, meta in session.tile_meta.items() if meta["pair_id"] == "t0" and meta["kind"] == "definition"
    )
    term_tile_b = next(tid for tid, meta in session.tile_meta.items() if meta["pair_id"] == "t1" and meta["kind"] == "term")

    # Wrong pair: no match recorded.
    state = session.answer(uow, {"first_tile_id": term_tile_a, "second_tile_id": term_tile_b})
    assert state["last_attempt"]["correct"] is False
    assert state["matched_count"] == 0

    # Correct pair.
    state = session.answer(uow, {"first_tile_id": term_tile_a, "second_tile_id": definition_tile_a})
    assert state["last_attempt"]["correct"] is True
    assert state["matched_count"] == 1
    assert state["finished"] is False  # one pair still unmatched


def test_match_session_raises_on_unknown_tile(tmp_path) -> None:
    uow, terms = _seed_terms(tmp_path, [("a", "1")])
    session = MatchSession("sess", "s1", GameMode.MATCH, terms)

    with pytest.raises(ValueError):
        session.answer(uow, {"first_tile_id": "nope", "second_tile_id": "also-nope"})


def test_test_session_input_question_scored_with_fuzzy_match(tmp_path, monkeypatch) -> None:
    # Force every question to be input-recall regardless of distractor pool
    # size, so this test doesn't depend on the random choice/input split.
    monkeypatch.setattr(game_modes.random, "random", lambda: 1.0)
    uow, terms = _seed_terms(tmp_path, [("a", "первое определение"), ("b", "второе определение")])
    session = QuizletTestSession("sess", "s1", GameMode.TEST, terms)
    assert all(q["type"] == "input" for q in session.questions)

    state = session.state()
    term = next(t for t in terms if t.id == state["term_id"])
    result = session.answer(uow, {"answer": term.definition})

    assert result["last_answer"]["correct"] is True
    assert result["score"] == 1


def test_test_session_choice_question_requires_exact_option_match(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(game_modes.random, "random", lambda: 0.0)
    monkeypatch.setattr(game_modes.random, "sample", lambda pool, k: pool[:k])
    monkeypatch.setattr(game_modes.random, "shuffle", lambda seq: None)
    uow, terms = _seed_terms(
        tmp_path, [("a", "def-a"), ("b", "def-b"), ("c", "def-c"), ("d", "def-d")]
    )
    session = QuizletTestSession("sess", "s1", GameMode.TEST, terms)
    assert all(q["type"] == "choice" for q in session.questions)

    state = session.state()
    term = next(t for t in terms if t.id == state["term_id"])
    assert term.definition in state["options"]

    wrong_option = next(o for o in state["options"] if o != term.definition)
    result = session.answer(uow, {"selected": wrong_option})
    assert result["last_answer"]["correct"] is False


def test_test_session_finishes_after_all_questions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(game_modes.random, "random", lambda: 1.0)
    uow, terms = _seed_terms(tmp_path, [("a", "1"), ("b", "2")])
    session = QuizletTestSession("sess", "s1", GameMode.TEST, terms)

    for _ in range(2):
        state = session.state()
        term = next(t for t in terms if t.id == state["term_id"])
        session.answer(uow, {"answer": term.definition})

    final_state = session.state()
    assert final_state["finished"] is True
    assert final_state["score"] == 2
    assert final_state["total"] == 2


def test_manager_start_answer_and_finish_persists_attempt(tmp_path) -> None:
    uow, _terms = _seed_terms(tmp_path, [("a", "первое определение")])

    session_id, state = game_modes.start(uow, "s1", GameMode.VOICE)
    assert state["finished"] is False

    result = game_modes.answer_spoken(uow, session_id, "первое определение")
    result = game_modes.answer_spoken(uow, session_id, "первое определение")
    assert result["finished"] is True

    with uow:
        attempts = uow.attempts.list_by_set("s1")
    assert len(attempts) == 1
    assert attempts[0].finished_at is not None
    assert attempts[0].score == 1 and attempts[0].total == 1


def test_manager_raises_for_unknown_session(tmp_path) -> None:
    with pytest.raises(UnknownSessionError):
        game_modes.get_state("does-not-exist")


def test_manager_start_raises_for_empty_set(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.sets.add(StudySet(id="empty", title="Empty", source=SetSource.MANUAL))
        uow.commit()

    with pytest.raises(ValueError):
        game_modes.start(uow, "empty", GameMode.FLASHCARDS)
