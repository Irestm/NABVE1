from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from modules.english_learning import cefr
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV


def test_parse_cefrj_csv_splits_variants_and_maps_pos() -> None:
    entries = set(cefr.parse_cefrj_csv(CEFR_CSV))

    assert ("figure", "VERB", "B1") in entries
    assert ("figure", "NOUN", "A2") in entries
    assert ("a.m.", "ADV", "A1") in entries
    assert ("am", "ADV", "A1") in entries


def test_parse_cefrj_csv_skips_unknown_levels_and_pos() -> None:
    text = "headword,pos,CEFR\nfoo,noun,Z9\nbar,gerund,A1\nbaz,noun,a2\n"

    assert list(cefr.parse_cefrj_csv(text)) == [("baz", "NOUN", "A2")]


def test_ensure_loaded_downloads_once(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    calls: list[int] = []

    def fetch() -> str:
        calls.append(1)
        return CEFR_CSV

    first = cefr.ensure_loaded(uow_factory, fetch)
    second = cefr.ensure_loaded(uow_factory, fetch)

    assert first == second > 0
    assert len(calls) == 1


def test_ensure_loaded_reports_network_failure(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    def fetch() -> str:
        raise httpx.ConnectError("offline")

    with pytest.raises(cefr.CefrUnavailableError):
        cefr.ensure_loaded(uow_factory, fetch)


def test_ensure_loaded_rejects_empty_download(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    with pytest.raises(cefr.CefrUnavailableError):
        cefr.ensure_loaded(uow_factory, lambda: "headword,pos,CEFR\n")


def test_lookup_prefers_exact_pos_then_lowest_level(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV)
    lookup = cefr.load_lookup(uow_factory)

    assert lookup.level("figure", "VERB") == "B1"
    assert lookup.level("Figure", "NOUN") == "A2"
    assert lookup.level("figure", "ADJ") == "A2"
    assert lookup.level("unknownword", "NOUN") is None
