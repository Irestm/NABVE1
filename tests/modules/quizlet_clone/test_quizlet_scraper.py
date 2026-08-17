from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.quizlet_clone import quizlet_scraper


def _link(href: str, title: str) -> MagicMock:
    link = MagicMock()
    link.get_attribute = AsyncMock(return_value=href)
    link.inner_text = AsyncMock(return_value=title)
    link.evaluate_handle = AsyncMock(side_effect=RuntimeError("no container"))
    return link


@pytest.mark.asyncio
async def test_list_library_sets_extracts_unique_sets_from_set_links() -> None:
    session = MagicMock()
    page = MagicMock()
    page.query_selector_all = AsyncMock(
        return_value=[
            _link("/123456/spanish-vocab/", "Spanish Vocab"),
            _link("/123456/spanish-vocab/", "Spanish Vocab"),  # duplicate link to the same set
            _link("/789012/german-verbs/", "German Verbs"),
            _link("/settings/", "Settings"),  # not a set URL — filtered out
        ]
    )
    session.library_page = AsyncMock(return_value=page)

    result = await quizlet_scraper.list_library_sets(session)

    assert {s.quizlet_set_id for s in result} == {"123456", "789012"}


@pytest.mark.asyncio
async def test_list_library_sets_raises_a_clear_error_when_nothing_found() -> None:
    session = MagicMock()
    page = MagicMock()
    page.query_selector_all = AsyncMock(return_value=[_link("/settings/", "Settings")])
    session.library_page = AsyncMock(return_value=page)

    with pytest.raises(RuntimeError, match="изменил структуру страницы"):
        await quizlet_scraper.list_library_sets(session)


def _term_element(text: str) -> MagicMock:
    element = MagicMock()
    element.inner_text = AsyncMock(return_value=text)
    return element


@pytest.mark.asyncio
async def test_scrape_set_terms_returns_pairs_from_the_first_working_selector() -> None:
    session = MagicMock()
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(
        side_effect=[
            [_term_element("hola"), _term_element("gato")],
            [_term_element("привет"), _term_element("кот")],
        ]
    )
    session.library_page = AsyncMock(return_value=page)

    pairs = await quizlet_scraper.scrape_set_terms(session, "123456")

    assert pairs == [("hola", "привет"), ("gato", "кот")]


@pytest.mark.asyncio
async def test_scrape_set_terms_raises_a_clear_error_when_every_selector_fails() -> None:
    session = MagicMock()
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock(side_effect=RuntimeError("selector not found"))
    session.library_page = AsyncMock(return_value=page)

    with pytest.raises(RuntimeError, match="изменил структуру страницы"):
        await quizlet_scraper.scrape_set_terms(session, "123456")
