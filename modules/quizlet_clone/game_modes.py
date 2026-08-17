from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any

from core.logger import get_logger
from core.voice.phrase_matching import fuzzy_contains_phrase
from modules.quizlet_clone.models import GameAttempt, GameMode, Term
from modules.quizlet_clone.storage import QuizletUnitOfWork

logger = get_logger(__name__)

# Typed test-mode input-recall answers are compared with a stricter
# threshold than spoken voice-mode answers (below) — typed text has none of
# STT's recognition noise, so a looser match there would just accept wrong
# answers.
TEST_ANSWER_FUZZY_THRESHOLD = 0.72
# Spoken answers vary far more than typed ones (word order, missing
# function words, STT mistakes) — see core.voice.phrase_matching, whose
# default 0.75 threshold was tuned for short stop/wake phrases, not full
# definition sentences.
VOICE_ANSWER_FUZZY_THRESHOLD = 0.55


class UnknownSessionError(Exception):
    pass


class GameOverError(Exception):
    """Raised when answer() is called on a session that already finished."""


class _BaseSession:
    def __init__(self, session_id: str, set_id: str, mode: GameMode, terms: list[Term]) -> None:
        self.session_id = session_id
        self.set_id = set_id
        self.mode = mode
        self.terms = terms
        self.started_at = datetime.now()
        self.finished = False
        self.attempt_id: int | None = None

    def _term_by_id(self, term_id: str) -> Term:
        for term in self.terms:
            if term.id == term_id:
                return term
        raise ValueError(f"Unknown term_id {term_id!r} for this session")

    def state(self) -> dict[str, Any]:
        raise NotImplementedError

    def answer(self, uow: QuizletUnitOfWork, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def score_and_total(self) -> tuple[int, int]:
        return 0, len(self.terms)


class FlashcardsSession(_BaseSession):
    """Plain browsing — no real "finished" state (the ТЗ describes this
    mode as free flipping/navigation, not a scored pass), so this session
    never sets self.finished; the user leaves the mode whenever they like."""

    def __init__(self, session_id: str, set_id: str, mode: GameMode, terms: list[Term]) -> None:
        super().__init__(session_id, set_id, mode, terms)
        self.index = 0
        self.flipped = False

    def state(self) -> dict[str, Any]:
        term = self.terms[self.index]
        return {
            "mode": "flashcards",
            "index": self.index,
            "total": len(self.terms),
            "flipped": self.flipped,
            "term": term.term,
            "definition": term.definition,
            "finished": False,
        }

    def answer(self, uow: QuizletUnitOfWork, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action == "flip":
            self.flipped = not self.flipped
        elif action in ("next", "prev"):
            delta = 1 if action == "next" else -1
            new_index = self.index + delta
            if 0 <= new_index < len(self.terms):
                self.index = new_index
                self.flipped = False
        else:
            raise ValueError(f"Unknown flashcards action: {action!r}")
        return self.state()


class LearnSession(_BaseSession):
    """Adaptive mode: each term needs to be answered correctly twice
    (net of misses) before it drops out of the pool; a wrong answer both
    persists to the term's times_wrong (so its selection weight stays high
    across future sessions too) and raises how many more correct answers
    this session still needs from it. random.choices' weights bias toward
    terms the user is currently missing more, without a full
    spaced-repetition scheduler — see the ТЗ's "не переусложнять"."""

    LEARNED_THRESHOLD = 2

    def __init__(self, session_id: str, set_id: str, mode: GameMode, terms: list[Term]) -> None:
        super().__init__(session_id, set_id, mode, terms)
        self.remaining_needed: dict[str, int] = {t.id: self.LEARNED_THRESHOLD for t in terms}
        self.current_term_id: str | None = self._pick_next()

    def _pick_next(self) -> str | None:
        pool = [term_id for term_id, needed in self.remaining_needed.items() if needed > 0]
        if not pool:
            return None
        weights = [self.remaining_needed[term_id] for term_id in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    def state(self) -> dict[str, Any]:
        if self.current_term_id is None:
            self.finished = True
            return {"mode": "learn", "finished": True, "total": len(self.terms)}
        term = self._term_by_id(self.current_term_id)
        remaining = sum(1 for needed in self.remaining_needed.values() if needed > 0)
        return {
            "mode": "learn",
            "finished": False,
            "term_id": term.id,
            "term": term.term,
            "definition": term.definition,
            "remaining": remaining,
            "total": len(self.terms),
        }

    def answer(self, uow: QuizletUnitOfWork, payload: dict[str, Any]) -> dict[str, Any]:
        term_id = payload.get("term_id")
        if term_id != self.current_term_id:
            raise ValueError("term_id does not match this session's current term")
        known = bool(payload.get("known"))
        with uow:
            uow.terms.record_answer(term_id, correct=known)
            uow.commit()
        if known:
            self.remaining_needed[term_id] = max(0, self.remaining_needed[term_id] - 1)
        else:
            self.remaining_needed[term_id] += 1
        self.current_term_id = self._pick_next()
        return self.state()

    def score_and_total(self) -> tuple[int, int]:
        return len(self.terms), len(self.terms)


class VoiceSession(LearnSession):
    """Same adaptive term-selection logic as LearnSession, driven by a
    spoken answer instead of a self-reported Знаю/Не знаю click. Correctness
    is decided by fuzzy-matching the STT transcription against the term's
    definition (core.voice.phrase_matching) rather than exact string
    equality, which would fail on virtually every real recognition. Kept
    free of any audio/STT/TTS import — core/main.py's voice routes own
    recording/transcribing/synthesizing and pass this plain transcribed
    text in, so the game logic stays testable without a real microphone."""

    def answer_spoken(self, uow: QuizletUnitOfWork, transcribed_text: str) -> dict[str, Any]:
        if self.current_term_id is None:
            raise GameOverError("Voice session already finished")
        term = self._term_by_id(self.current_term_id)
        correct = bool(transcribed_text.strip()) and fuzzy_contains_phrase(
            transcribed_text, term.definition, threshold=VOICE_ANSWER_FUZZY_THRESHOLD
        )
        result = self.answer(uow, {"term_id": term.id, "known": correct})
        result["correct"] = correct
        result["answered_term"] = term.term
        result["expected_definition"] = term.definition
        result["transcribed_text"] = transcribed_text
        return result


class MatchSession(_BaseSession):
    """Term tiles and definition tiles are shuffled independently (not as
    matched pairs) so a term never sits next to its own definition, then
    exposed to the client as one flat, further-shuffled tile list — the
    client only ever learns which pair_id a tile belongs to by successfully
    matching it (see state())."""

    def __init__(self, session_id: str, set_id: str, mode: GameMode, terms: list[Term]) -> None:
        super().__init__(session_id, set_id, mode, terms)
        term_tiles = [(uuid.uuid4().hex, t.id, t.term, "term") for t in terms]
        definition_tiles = [(uuid.uuid4().hex, t.id, t.definition, "definition") for t in terms]
        all_tiles = term_tiles + definition_tiles
        random.shuffle(all_tiles)
        self.tile_meta: dict[str, dict[str, Any]] = {
            tile_id: {"pair_id": pair_id, "text": text, "kind": kind} for tile_id, pair_id, text, kind in all_tiles
        }
        self.matched: set[str] = set()
        self.elapsed_seconds: float | None = None
        self.last_attempt: dict[str, Any] | None = None

    def state(self) -> dict[str, Any]:
        tiles = [
            {"tile_id": tile_id, "text": meta["text"], "kind": meta["kind"], "matched": meta["pair_id"] in self.matched}
            for tile_id, meta in self.tile_meta.items()
        ]
        return {
            "mode": "match",
            "tiles": tiles,
            "matched_count": len(self.matched),
            "total": len(self.terms),
            "finished": self.finished,
            "elapsed_seconds": self.elapsed_seconds,
            "last_attempt": self.last_attempt,
        }

    def answer(self, uow: QuizletUnitOfWork, payload: dict[str, Any]) -> dict[str, Any]:
        first_id, second_id = payload.get("first_tile_id"), payload.get("second_tile_id")
        first_meta, second_meta = self.tile_meta.get(first_id), self.tile_meta.get(second_id)
        if first_meta is None or second_meta is None:
            raise ValueError("Unknown tile id")

        is_match = (
            first_meta["pair_id"] == second_meta["pair_id"]
            and first_meta["kind"] != second_meta["kind"]
            and first_meta["pair_id"] not in self.matched
        )
        if is_match:
            self.matched.add(first_meta["pair_id"])
            with uow:
                uow.terms.record_answer(first_meta["pair_id"], correct=True)
                uow.commit()
        self.last_attempt = {"first_tile_id": first_id, "second_tile_id": second_id, "correct": is_match}

        if len(self.matched) == len(self.terms):
            self.finished = True
            self.elapsed_seconds = round((datetime.now() - self.started_at).total_seconds(), 1)
        return self.state()

    def score_and_total(self) -> tuple[int, int]:
        return len(self.matched), len(self.terms)


class TestSession(_BaseSession):
    """Mixed input-recall / multiple-choice, per term, roughly 50/50 when
    enough distractor definitions exist. Multiple-choice distractors are
    drawn first from the rest of this set's own definitions, topped up from
    `distractor_pool` (other sets' definitions, passed in by the caller —
    see modules.quizlet_clone.handlers) when this set alone doesn't have
    at least 3 other terms; a term still short on distractors after that
    always gets an input-recall question instead."""

    def __init__(
        self, session_id: str, set_id: str, mode: GameMode, terms: list[Term], distractor_pool: list[str] | None = None
    ) -> None:
        super().__init__(session_id, set_id, mode, terms)
        distractor_pool = distractor_pool or []
        self.questions: list[dict[str, Any]] = []
        for term in terms:
            own_pool = [t.definition for t in terms if t.id != term.id]
            combined_pool = own_pool + distractor_pool
            if len(combined_pool) >= 3 and random.random() < 0.5:
                distractors = random.sample(combined_pool, 3)
                options = distractors + [term.definition]
                random.shuffle(options)
                self.questions.append({"term_id": term.id, "type": "choice", "options": options})
            else:
                self.questions.append({"term_id": term.id, "type": "input"})
        random.shuffle(self.questions)
        self.index = 0
        self.score = 0

    def state(self) -> dict[str, Any]:
        if self.index >= len(self.questions):
            self.finished = True
            return {"mode": "test", "finished": True, "score": self.score, "total": len(self.questions)}
        question = self.questions[self.index]
        term = self._term_by_id(question["term_id"])
        result: dict[str, Any] = {
            "mode": "test",
            "finished": False,
            "index": self.index,
            "total": len(self.questions),
            "term_id": term.id,
            "term": term.term,
            "type": question["type"],
            "score": self.score,
        }
        if question["type"] == "choice":
            result["options"] = question["options"]
        return result

    def answer(self, uow: QuizletUnitOfWork, payload: dict[str, Any]) -> dict[str, Any]:
        if self.index >= len(self.questions):
            raise GameOverError("This test session already finished")
        question = self.questions[self.index]
        term = self._term_by_id(question["term_id"])

        if question["type"] == "choice":
            correct = payload.get("selected", "").strip() == term.definition.strip()
        else:
            correct = fuzzy_contains_phrase(
                payload.get("answer", ""), term.definition, threshold=TEST_ANSWER_FUZZY_THRESHOLD
            )

        with uow:
            uow.terms.record_answer(term.id, correct=correct)
            uow.commit()
        if correct:
            self.score += 1
        last_answer = {"term_id": term.id, "correct": correct, "correct_definition": term.definition}
        self.index += 1

        result = self.state()
        result["last_answer"] = last_answer
        return result

    def score_and_total(self) -> tuple[int, int]:
        return self.score, len(self.questions)


_SESSIONS: dict[str, _BaseSession] = {}

_SESSION_CLASSES = {
    GameMode.FLASHCARDS: FlashcardsSession,
    GameMode.LEARN: LearnSession,
    GameMode.MATCH: MatchSession,
    GameMode.VOICE: VoiceSession,
}


def start(
    uow: QuizletUnitOfWork, set_id: str, mode: GameMode, *, distractor_pool: list[str] | None = None
) -> tuple[str, dict[str, Any]]:
    with uow:
        terms = uow.terms.list_by_set(set_id)
    if not terms:
        raise ValueError("Набор не содержит терминов — сначала добавьте хотя бы одну пару термин/определение.")

    session_id = uuid.uuid4().hex
    if mode is GameMode.TEST:
        session: _BaseSession = TestSession(session_id, set_id, mode, terms, distractor_pool)
    else:
        session_cls = _SESSION_CLASSES.get(mode)
        if session_cls is None:
            raise ValueError(f"Unknown game mode: {mode}")
        session = session_cls(session_id, set_id, mode, terms)

    _SESSIONS[session_id] = session
    _record_attempt_start(uow, session)
    return session_id, session.state()


def get_session(session_id: str) -> _BaseSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise UnknownSessionError(session_id)
    return session


def get_state(session_id: str) -> dict[str, Any]:
    return get_session(session_id).state()


def answer(uow: QuizletUnitOfWork, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = get_session(session_id)
    was_finished = session.finished
    state = session.answer(uow, payload)
    if session.finished and not was_finished:
        _record_attempt_finish(uow, session)
    return state


def answer_spoken(uow: QuizletUnitOfWork, session_id: str, transcribed_text: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not isinstance(session, VoiceSession):
        raise ValueError("This session is not a voice session")
    was_finished = session.finished
    result = session.answer_spoken(uow, transcribed_text)
    if session.finished and not was_finished:
        _record_attempt_finish(uow, session)
    return result


def _record_attempt_start(uow: QuizletUnitOfWork, session: _BaseSession) -> None:
    attempt = GameAttempt(
        id=None, set_id=session.set_id, mode=session.mode, started_at=session.started_at, finished_at=None, score=0, total=0
    )
    with uow:
        session.attempt_id = uow.attempts.add(attempt)
        uow.commit()


def _record_attempt_finish(uow: QuizletUnitOfWork, session: _BaseSession) -> None:
    if session.attempt_id is None:
        return
    score, total = session.score_and_total()
    with uow:
        uow.attempts.finish(session.attempt_id, score=score, total=total, finished_at=datetime.now())
        uow.commit()
    logger.info("Quizlet game attempt finished: set=%s mode=%s score=%d/%d", session.set_id, session.mode.value, score, total)
