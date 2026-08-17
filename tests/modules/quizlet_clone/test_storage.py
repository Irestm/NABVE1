from __future__ import annotations

from datetime import datetime

from modules.quizlet_clone.models import GameAttempt, GameMode, SetSource, StudySet, Term
from modules.quizlet_clone.storage import QuizletUnitOfWork


def _uow(tmp_path) -> QuizletUnitOfWork:
    return QuizletUnitOfWork(tmp_path / "assistant.db")


def test_add_and_get_set(tmp_path) -> None:
    uow = _uow(tmp_path)
    study_set = StudySet(id="s1", title="Биология", source=SetSource.MANUAL)

    with uow:
        uow.sets.add(study_set)
        uow.commit()
        fetched = uow.sets.get("s1")

    assert fetched is not None
    assert fetched.title == "Биология"
    assert fetched.source is SetSource.MANUAL
    assert fetched.created_at is not None


def test_get_by_quizlet_id_finds_imported_set(tmp_path) -> None:
    uow = _uow(tmp_path)
    study_set = StudySet(id="s1", title="Испанский", source=SetSource.QUIZLET_IMPORT, quizlet_set_id="123456")

    with uow:
        uow.sets.add(study_set)
        uow.commit()
        fetched = uow.sets.get_by_quizlet_id("123456")
        missing = uow.sets.get_by_quizlet_id("does-not-exist")

    assert fetched is not None
    assert fetched.id == "s1"
    assert missing is None


def test_terms_round_trip_and_record_answer_updates_counters(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.sets.add(StudySet(id="s1", title="Set", source=SetSource.MANUAL))
        uow.terms.add(Term(id="t1", set_id="s1", term="кошка", definition="cat", position=0))
        uow.commit()

    with uow:
        uow.terms.record_answer("t1", correct=True)
        uow.terms.record_answer("t1", correct=False)
        uow.commit()
        term = uow.terms.get("t1")

    assert term is not None
    assert term.times_seen == 2
    assert term.times_correct == 1
    assert term.times_wrong == 1


def test_delete_by_set_removes_only_that_sets_terms(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.sets.add(StudySet(id="s1", title="A", source=SetSource.MANUAL))
        uow.sets.add(StudySet(id="s2", title="B", source=SetSource.MANUAL))
        uow.terms.add(Term(id="t1", set_id="s1", term="a", definition="1", position=0))
        uow.terms.add(Term(id="t2", set_id="s2", term="b", definition="2", position=0))
        uow.commit()

    with uow:
        uow.terms.delete_by_set("s1")
        uow.commit()

    with uow:
        assert uow.terms.list_by_set("s1") == []
        assert len(uow.terms.list_by_set("s2")) == 1


def test_game_attempts_start_and_finish(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.sets.add(StudySet(id="s1", title="Set", source=SetSource.MANUAL))
        attempt = GameAttempt(
            id=None, set_id="s1", mode=GameMode.LEARN, started_at=datetime.now(), finished_at=None, score=0, total=0
        )
        attempt_id = uow.attempts.add(attempt)
        uow.commit()

    with uow:
        uow.attempts.finish(attempt_id, score=5, total=5, finished_at=datetime.now())
        uow.commit()
        stored = uow.attempts.get(attempt_id)

    assert stored is not None
    assert stored.score == 5
    assert stored.total == 5
    assert stored.finished_at is not None
