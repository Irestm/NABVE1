from __future__ import annotations

import csv
import io
import threading
from collections.abc import Callable, Iterator

import httpx

from core.logger import get_logger
from modules.english_learning.domain import CEFR_LEVELS
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

CEFRJ_URL = (
    "https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/cefrj-vocabulary-profile-1.5.csv"
)
CEFRJ_ATTRIBUTION = (
    "The CEFR-J Wordlist Version 1.5. Compiled by Yukio Tono, Tokyo University of Foreign Studies. "
    "http://www.cefr-j.org/download.html — via github.com/openlanguageprofiles/olp-en-cefrj"
)
_DOWNLOAD_TIMEOUT_SECONDS = 30.0

POS_TO_UPOS: dict[str, tuple[str, ...]] = {
    "noun": ("NOUN",),
    "verb": ("VERB",),
    "adjective": ("ADJ",),
    "adverb": ("ADV",),
    "pronoun": ("PRON",),
    "preposition": ("ADP",),
    "determiner": ("DET",),
    "conjunction": ("CCONJ", "SCONJ"),
    "number": ("NUM",),
    "interjection": ("INTJ",),
    "modal auxiliary": ("AUX",),
    "be-verb": ("AUX", "VERB"),
    "do-verb": ("AUX", "VERB"),
    "have-verb": ("AUX", "VERB"),
}

_load_lock = threading.Lock()


class CefrUnavailableError(RuntimeError):
    pass


def parse_cefrj_csv(text: str) -> Iterator[tuple[str, str, str]]:
    for row in csv.DictReader(io.StringIO(text)):
        level = (row.get("CEFR") or "").strip().upper()
        pos = (row.get("pos") or "").strip().lower()
        if level not in CEFR_LEVELS or pos not in POS_TO_UPOS:
            continue
        for variant in (row.get("headword") or "").split("/"):
            headword = variant.strip().lower()
            if not headword:
                continue
            for upos in POS_TO_UPOS[pos]:
                yield headword, upos, level


def _download() -> str:
    response = httpx.get(CEFRJ_URL, timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True)
    response.raise_for_status()
    return response.text


def ensure_loaded(
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    fetch: Callable[[], str] = _download,
) -> int:
    with _load_lock:
        with uow_factory() as uow:
            existing = uow.cefr.count()
        if existing:
            return existing
        try:
            text = fetch()
        except httpx.HTTPError as exc:
            raise CefrUnavailableError(
                "Не удалось скачать словарь CEFR-J — проверьте интернет и попробуйте ещё раз."
            ) from exc
        entries = list(parse_cefrj_csv(text))
        if not entries:
            raise CefrUnavailableError("Скачанный словарь CEFR-J пуст или в неожиданном формате.")
        with uow_factory() as uow:
            uow.cefr.replace_all(entries)
            uow.commit()
            loaded = uow.cefr.count()
        logger.info("Loaded %d CEFR-J entries", loaded)
        return loaded


class CefrLookup:
    def __init__(self, index: dict[tuple[str, str], str]) -> None:
        self._index = index
        self._any_pos: dict[str, str] = {}
        for (headword, _pos), level in index.items():
            current = self._any_pos.get(headword)
            if current is None or CEFR_LEVELS.index(level) < CEFR_LEVELS.index(current):
                self._any_pos[headword] = level

    def level(self, lemma: str, pos: str) -> str | None:
        key = lemma.lower()
        return self._index.get((key, pos)) or self._any_pos.get(key)

    def __len__(self) -> int:
        return len(self._index)


def load_lookup(uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork) -> CefrLookup:
    with uow_factory() as uow:
        return CefrLookup(uow.cefr.load_index())
