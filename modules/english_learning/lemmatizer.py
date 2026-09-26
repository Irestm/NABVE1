from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

SPACY_MODEL = "en_core_web_sm"
_PERSON_LIKE_ENTITIES = frozenset({"PERSON", "GPE", "LOC", "ORG", "NORP", "FAC"})


class LemmatizerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalyzedToken:
    text: str
    lemma: str
    pos: str
    is_stop: bool
    is_alpha: bool
    like_num: bool
    is_named_entity: bool


class Lemmatizer(Protocol):
    def analyze(self, texts: Iterable[str]) -> Iterator[list[AnalyzedToken]]: ...


class SpacyLemmatizer:
    def __init__(self, model_name: str = SPACY_MODEL) -> None:
        self._model_name = model_name
        self._nlp: Any = None
        self._lock = threading.Lock()

    def _pipeline(self) -> Any:
        with self._lock:
            if self._nlp is None:
                try:
                    import spacy
                except ImportError as exc:
                    raise LemmatizerUnavailableError("Не установлен spaCy: pip install spacy") from exc
                try:
                    self._nlp = spacy.load(self._model_name, disable=["parser"])
                except OSError as exc:
                    raise LemmatizerUnavailableError(
                        f"Не установлена модель spaCy: python -m spacy download {self._model_name}"
                    ) from exc
            return self._nlp

    def analyze(self, texts: Iterable[str]) -> Iterator[list[AnalyzedToken]]:
        nlp = self._pipeline()
        for doc in nlp.pipe(texts, batch_size=256):
            yield [
                AnalyzedToken(
                    text=token.text,
                    lemma=token.lemma_,
                    pos=token.pos_,
                    is_stop=token.is_stop,
                    is_alpha=token.is_alpha,
                    like_num=token.like_num,
                    is_named_entity=token.ent_type_ in _PERSON_LIKE_ENTITIES,
                )
                for token in doc
            ]


_shared: SpacyLemmatizer | None = None


def get_lemmatizer() -> SpacyLemmatizer:
    global _shared
    if _shared is None:
        _shared = SpacyLemmatizer()
    return _shared
