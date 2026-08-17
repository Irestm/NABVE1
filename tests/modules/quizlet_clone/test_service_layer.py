from __future__ import annotations

from modules.quizlet_clone import service_layer
from modules.quizlet_clone.models import SetSource
from modules.quizlet_clone.storage import QuizletUnitOfWork


def _uow(tmp_path) -> QuizletUnitOfWork:
    return QuizletUnitOfWork(tmp_path / "assistant.db")


def test_create_manual_set_persists_terms_in_order(tmp_path) -> None:
    uow = _uow(tmp_path)

    study_set = service_layer.create_manual_set(uow, "Испанский", [("hola", "привет"), ("gato", "кот")])

    assert study_set.source is SetSource.MANUAL
    assert [t.term for t in study_set.terms] == ["hola", "gato"]
    assert [t.definition for t in study_set.terms] == ["привет", "кот"]
    assert study_set.progress_percent == 0


def test_update_set_replaces_title_and_terms(tmp_path) -> None:
    uow = _uow(tmp_path)
    study_set = service_layer.create_manual_set(uow, "Old", [("a", "1")])

    updated = service_layer.update_set(uow, study_set.id, "New", [("b", "2"), ("c", "3")])

    assert updated is not None
    assert updated.title == "New"
    assert [t.term for t in updated.terms] == ["b", "c"]


def test_update_set_returns_none_for_unknown_id(tmp_path) -> None:
    uow = _uow(tmp_path)

    assert service_layer.update_set(uow, "does-not-exist", "X", [("a", "1")]) is None


def test_delete_set_removes_set_and_its_terms(tmp_path) -> None:
    uow = _uow(tmp_path)
    study_set = service_layer.create_manual_set(uow, "Set", [("a", "1")])

    removed = service_layer.delete_set(uow, study_set.id)

    assert removed is True
    assert service_layer.get_set(uow, study_set.id) is None
    assert service_layer.delete_set(uow, study_set.id) is False


def test_import_or_refresh_set_creates_new_set(tmp_path) -> None:
    uow = _uow(tmp_path)

    study_set = service_layer.import_or_refresh_set(uow, "999", "Немецкий", [("Hund", "собака")])

    assert study_set.source is SetSource.QUIZLET_IMPORT
    assert study_set.quizlet_set_id == "999"
    assert [t.term for t in study_set.terms] == ["Hund"]


def test_import_or_refresh_set_refreshes_existing_set_and_carries_over_stats(tmp_path) -> None:
    uow = _uow(tmp_path)
    first = service_layer.import_or_refresh_set(uow, "999", "Немецкий", [("Hund", "собака"), ("Katze", "кошка")])
    with uow:
        uow.terms.record_answer(first.terms[0].id, correct=True)
        uow.terms.record_answer(first.terms[0].id, correct=True)
        uow.commit()

    refreshed = service_layer.import_or_refresh_set(uow, "999", "Немецкий (обновлено)", [("Hund", "собака"), ("Maus", "мышь")])

    assert refreshed.id == first.id
    assert refreshed.title == "Немецкий (обновлено)"
    terms_by_text = {t.term: t for t in refreshed.terms}
    assert terms_by_text["Hund"].times_correct == 2
    assert terms_by_text["Maus"].times_correct == 0
    assert "Katze" not in terms_by_text
