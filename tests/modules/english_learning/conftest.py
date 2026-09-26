from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pytest

from modules.english_learning import subtitle_store
from modules.english_learning.lemmatizer import AnalyzedToken
from modules.english_learning.uow import EnglishUnitOfWork

CEFR_CSV = """headword,pos,CEFR,CoreInventory 1,CoreInventory 2,Threshold
figure,verb,B1,,,
figure,noun,A2,,,
decide,verb,A2,,,
honest,adjective,B1,,,
house,noun,A1,,,
consequence,noun,B2,,,
a.m./am,adverb,A1,,,
"""

STOP_WORDS = frozenset({"i", "it", "the", "a", "to", "you", "we", "be", "do", "out", "have"})
PROPER = frozenset({"John", "Walter", "Albuquerque"})
POS = {
    "figure": "VERB",
    "figured": "VERB",
    "decide": "VERB",
    "decided": "VERB",
    "honest": "ADJ",
    "house": "NOUN",
    "consequences": "NOUN",
    "dude": "NOUN",
    "yo": "INTJ",
}
LEMMAS = {"figured": "figure", "decided": "decide", "consequences": "consequence"}


class FakeLemmatizer:
    def analyze(self, texts: Iterable[str]) -> Iterator[list[AnalyzedToken]]:
        for text in texts:
            tokens: list[AnalyzedToken] = []
            for raw in text.replace(",", " ").replace(".", " ").replace("?", " ").replace("!", " ").split():
                lower = raw.lower()
                tokens.append(
                    AnalyzedToken(
                        text=raw,
                        lemma=LEMMAS.get(lower, lower),
                        pos="PROPN" if raw in PROPER else POS.get(lower, "NOUN" if raw.isalpha() else "NUM"),
                        is_stop=lower in STOP_WORDS,
                        is_alpha=raw.isalpha(),
                        like_num=raw.isdigit(),
                        is_named_entity=raw in PROPER,
                    )
                )
            yield tokens


@pytest.fixture
def uow_factory(tmp_path: Path) -> Callable[[], EnglishUnitOfWork]:
    db_path = tmp_path / "english.db"
    return lambda: EnglishUnitOfWork(db_path)


@pytest.fixture(autouse=True)
def _subtitles_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "subtitles"
    monkeypatch.setattr(subtitle_store, "SUBTITLES_DIR", directory)
    return directory


@pytest.fixture
def fake_lemmatizer() -> FakeLemmatizer:
    return FakeLemmatizer()
