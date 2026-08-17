from __future__ import annotations

import uuid

from core.logger import get_logger
from modules.quizlet_clone.models import SetSource, StudySet, Term
from modules.quizlet_clone.storage import QuizletUnitOfWork

logger = get_logger(__name__)


def _set_with_terms(uow: QuizletUnitOfWork, study_set: StudySet) -> StudySet:
    study_set.terms = uow.terms.list_by_set(study_set.id)
    study_set.attempts_count = len(uow.attempts.list_by_set(study_set.id))
    return study_set


def list_sets(uow: QuizletUnitOfWork) -> list[StudySet]:
    with uow:
        sets = uow.sets.list_all()
        return [_set_with_terms(uow, s) for s in sets]


def get_set(uow: QuizletUnitOfWork, set_id: str) -> StudySet | None:
    with uow:
        study_set = uow.sets.get(set_id)
        if study_set is None:
            return None
        return _set_with_terms(uow, study_set)


def create_manual_set(uow: QuizletUnitOfWork, title: str, terms: list[tuple[str, str]]) -> StudySet:
    study_set = StudySet(id=uuid.uuid4().hex, title=title, source=SetSource.MANUAL)
    with uow:
        uow.sets.add(study_set)
        for position, (term_text, definition) in enumerate(terms):
            uow.terms.add(
                Term(id=uuid.uuid4().hex, set_id=study_set.id, term=term_text, definition=definition, position=position)
            )
        uow.commit()
    return get_set(uow, study_set.id)  # type: ignore[return-value]


def update_set(uow: QuizletUnitOfWork, set_id: str, title: str, terms: list[tuple[str, str]]) -> StudySet | None:
    """Full replace of a manual set's title/terms — simplest correct
    behavior for the ТЗ's "простая форма добавления термин/определение";
    per-term stats reset along with the terms they belonged to, same as
    deleting and recreating the set would do."""
    with uow:
        existing = uow.sets.get(set_id)
        if existing is None:
            return None
        uow.sets.update_title(set_id, title)
        uow.terms.delete_by_set(set_id)
        for position, (term_text, definition) in enumerate(terms):
            uow.terms.add(
                Term(id=uuid.uuid4().hex, set_id=set_id, term=term_text, definition=definition, position=position)
            )
        uow.commit()
    return get_set(uow, set_id)


def delete_set(uow: QuizletUnitOfWork, set_id: str) -> bool:
    with uow:
        removed = uow.sets.delete(set_id)
        if removed:
            uow.terms.delete_by_set(set_id)
        uow.commit()
    return removed


def import_or_refresh_set(uow: QuizletUnitOfWork, quizlet_set_id: str, title: str, terms: list[tuple[str, str]]) -> StudySet:
    """Creates a new imported StudySet, or — if this Quizlet set was already
    imported before — replaces its terms in place (ТЗ п.1: "обновить"),
    preserving existing per-term stats for terms whose text didn't change so
    progress isn't wiped by an ordinary refresh."""
    with uow:
        existing = uow.sets.get_by_quizlet_id(quizlet_set_id)
        if existing is None:
            study_set = StudySet(id=uuid.uuid4().hex, title=title, source=SetSource.QUIZLET_IMPORT, quizlet_set_id=quizlet_set_id)
            uow.sets.add(study_set)
            set_id = study_set.id
            previous_terms: dict[str, Term] = {}
        else:
            set_id = existing.id
            uow.sets.update_title(set_id, title)
            previous_terms = {t.term: t for t in uow.terms.list_by_set(set_id)}
            uow.terms.delete_by_set(set_id)

        for position, (term_text, definition) in enumerate(terms):
            carried = previous_terms.get(term_text)
            uow.terms.add(
                Term(
                    id=uuid.uuid4().hex,
                    set_id=set_id,
                    term=term_text,
                    definition=definition,
                    position=position,
                    times_seen=carried.times_seen if carried else 0,
                    times_correct=carried.times_correct if carried else 0,
                    times_wrong=carried.times_wrong if carried else 0,
                )
            )
        uow.commit()
    logger.info("Imported/refreshed Quizlet set %s (%d terms)", quizlet_set_id, len(terms))
    return get_set(uow, set_id)  # type: ignore[return-value]
