from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.quizlet_clone import quizlet_scraper


def _mock_page() -> MagicMock:
    # quizlet_scraper._scroll_and_collect calls page.evaluate (to read
    # document.body.scrollHeight) and page.wait_for_timeout on every round
    # of its scroll-and-rescan loop — a bare MagicMock's auto-generated
    # attributes for those aren't awaitable, so every test that goes
    # through list_library_sets/scrape_set_terms needs them mocked async,
    # not just the ones that used to need query_selector_all before that
    # loop existed.
    #
    # page.url defaults to already being on the user's own library — the
    # happy-path landing spot list_library_sets now requires (see its own
    # "Must actually be on /user/<name>/sets" check) — since most of these
    # tests are about what happens once scanning that page, not about the
    # click-through navigation itself. Tests for the navigation failure case
    # override this back to the general activity feed.
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=1000)
    page.wait_for_timeout = AsyncMock()
    page.url = "https://quizlet.com/user/testuser/sets"
    return page


def _link(href: str, title: str) -> MagicMock:
    link = MagicMock()
    link.get_attribute = AsyncMock(return_value=href)
    link.inner_text = AsyncMock(return_value=title)
    link.evaluate_handle = AsyncMock(side_effect=RuntimeError("no container"))
    return link


@pytest.mark.asyncio
async def test_list_library_sets_extracts_unique_sets_from_set_links() -> None:
    session = MagicMock()
    page = _mock_page()
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
async def test_list_library_sets_matches_absolute_links_with_a_locale_segment_and_query_string() -> None:
    # Confirmed live (2026-08-18): the library page's actual links look like
    # this now, not the old plain root-relative /<id>/<slug>/ shape — see
    # _SET_LINK_PATTERN's own comment.
    session = MagicMock()
    page = _mock_page()
    page.query_selector_all = AsyncMock(
        return_value=[
            _link(
                "https://quizlet.com/ua/1167673341/from-listening-tests-flash-cards"
                "?funnelUUID=78bc975d-dd58-4555-9c7d-1cc568e0956c",
                "From listening tests",
            ),
        ]
    )
    session.library_page = AsyncMock(return_value=page)

    result = await quizlet_scraper.list_library_sets(session)

    assert {s.quizlet_set_id for s in result} == {"1167673341"}


@pytest.mark.asyncio
async def test_list_library_sets_clicks_through_to_the_users_own_library() -> None:
    # /latest (session.library_page()'s default landing page) renders its
    # set cards as JS widgets with no plain <a href> — list_library_sets
    # must follow the "your library" nav link (matched structurally, by
    # href shape) to a page that actually has scrapeable set links.
    session = MagicMock()
    page = _mock_page()
    page.query_selector_all = AsyncMock(
        return_value=[_link("/123456/spanish-vocab/", "Spanish Vocab")]
    )
    page.wait_for_url = AsyncMock()
    my_library_link = MagicMock()
    my_library_link.count = AsyncMock(return_value=1)
    my_library_link.evaluate = AsyncMock()
    locator = MagicMock()
    locator.first = my_library_link
    page.locator = MagicMock(return_value=locator)
    session.library_page = AsyncMock(return_value=page)

    result = await quizlet_scraper.list_library_sets(session)

    page.locator.assert_called_once_with("a[href^='/user/'][href$='/sets']")
    my_library_link.evaluate.assert_awaited_once_with("el => el.click()")
    page.wait_for_url.assert_awaited_once()
    assert {s.quizlet_set_id for s in result} == {"123456"}


@pytest.mark.asyncio
async def test_list_library_sets_accumulates_sets_revealed_across_multiple_scroll_rounds() -> None:
    # Regression test for the reported bug: a virtualized library page only
    # has a handful of set links in the DOM at any moment, revealing more
    # as _scroll_and_collect scrolls further — scanning once, right after
    # load, silently capped the result at whatever the first screenful
    # happened to contain regardless of the library's real size.
    session = MagicMock()
    page = _mock_page()
    all_links = [_link(f"/{100000 + i}/set-{i}/", f"Set {i}") for i in range(5)]
    call_count = {"n": 0}

    async def query_selector_all(_selector: str) -> list[MagicMock]:
        call_count["n"] += 1
        revealed = min(call_count["n"] * 2, len(all_links))
        return all_links[:revealed]

    page.query_selector_all = AsyncMock(side_effect=query_selector_all)
    session.library_page = AsyncMock(return_value=page)

    result = await quizlet_scraper.list_library_sets(session)

    assert {s.quizlet_set_id for s in result} == {str(100000 + i) for i in range(5)}


@pytest.mark.asyncio
async def test_list_library_sets_raises_when_never_reaching_the_users_own_library() -> None:
    # Regression test for the reported bug: when the "your library" nav link
    # can't be found/clicked (stale selector after a redesign), the old
    # behavior silently fell back to scanning whatever page we're still on —
    # quizlet_auth.LIBRARY_URL's general activity/recommendation feed, NOT
    # the user's own sets — which is how other people's/recommended sets
    # ended up mixed into "Библиотека Quizlet". Now it must fail loudly
    # instead of returning that wrong data.
    session = MagicMock()
    page = _mock_page()
    page.url = "https://quizlet.com/latest"  # never navigated away from this
    page.query_selector_all = AsyncMock(
        return_value=[_link("/123456/some-other-persons-set/", "Not mine")]
    )
    session.library_page = AsyncMock(return_value=page)

    with pytest.raises(RuntimeError, match="личную библиотеку"):
        await quizlet_scraper.list_library_sets(session)
    page.query_selector_all.assert_not_called()


@pytest.mark.asyncio
async def test_list_library_sets_raises_a_clear_error_when_nothing_found() -> None:
    session = MagicMock()
    page = _mock_page()
    page.query_selector_all = AsyncMock(return_value=[_link("/settings/", "Settings")])
    session.library_page = AsyncMock(return_value=page)

    with pytest.raises(RuntimeError, match="изменил структуру страницы"):
        await quizlet_scraper.list_library_sets(session)


def _term_element(text: str) -> MagicMock:
    element = MagicMock()
    element.inner_text = AsyncMock(return_value=text)
    return element


@pytest.mark.asyncio
async def test_scrape_set_terms_returns_pairs_from_the_card_side_selector() -> None:
    # Confirmed live (2026-08-18): this is what the set page actually
    # renders now — one element per side (term, definition), strictly
    # alternating, under a single selector rather than two parallel ones.
    session = MagicMock()
    page = _mock_page()
    page.goto = AsyncMock()
    page.query_selector_all = AsyncMock(
        return_value=[
            _term_element("hola"),
            _term_element("привет"),
            _term_element("gato"),
            _term_element("кот"),
        ]
    )
    session.library_page = AsyncMock(return_value=page)

    pairs = await quizlet_scraper.scrape_set_terms(session, "123456")

    assert pairs == [("hola", "привет"), ("gato", "кот")]


@pytest.mark.asyncio
async def test_scrape_set_terms_accumulates_terms_revealed_across_multiple_scroll_rounds() -> None:
    # Regression test for the reported bug: a set with many terms returned
    # the exact same fixed count as a small one, because scanning happened
    # once, before a virtualized term list had rendered anything past the
    # first screenful.
    session = MagicMock()
    page = _mock_page()
    page.goto = AsyncMock()
    all_sides = [
        _term_element(t) for pair in [("hola", "привет"), ("gato", "кот"), ("perro", "собака")] for t in pair
    ]
    call_count = {"n": 0}

    async def query_selector_all(_selector: str) -> list[MagicMock]:
        call_count["n"] += 1
        revealed = min(call_count["n"] * 4, len(all_sides))
        return all_sides[:revealed]

    page.query_selector_all = AsyncMock(side_effect=query_selector_all)
    session.library_page = AsyncMock(return_value=page)

    pairs = await quizlet_scraper.scrape_set_terms(session, "123456")

    assert pairs == [("hola", "привет"), ("gato", "кот"), ("perro", "собака")]


@pytest.mark.asyncio
async def test_scrape_set_terms_falls_back_to_a_selector_pair_when_card_sides_are_absent() -> None:
    session = MagicMock()
    page = _mock_page()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    term_selector, definition_selector = quizlet_scraper._TERM_DEFINITION_SELECTOR_PAIRS[0]

    # A plain positional side_effect list assumes exactly one
    # query_selector_all call per selector — no longer true now that the
    # card-side selector is retried a couple of times (by
    # _scroll_and_collect, waiting to see if scrolling reveals anything)
    # before falling back at all. Branch on the actual selector instead.
    async def query_selector_all(selector: str) -> list[MagicMock]:
        if selector == quizlet_scraper._TERM_CARD_SIDE_SELECTOR:
            return []  # nothing on this (older-layout) page
        if selector == term_selector:
            return [_term_element("hola"), _term_element("gato")]
        if selector == definition_selector:
            return [_term_element("привет"), _term_element("кот")]
        return []

    page.query_selector_all = AsyncMock(side_effect=query_selector_all)
    session.library_page = AsyncMock(return_value=page)

    pairs = await quizlet_scraper.scrape_set_terms(session, "123456")

    assert pairs == [("hola", "привет"), ("gato", "кот")]


@pytest.mark.asyncio
async def test_scrape_set_terms_raises_a_clear_error_when_every_selector_fails() -> None:
    session = MagicMock()
    page = _mock_page()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock(side_effect=RuntimeError("selector not found"))
    session.library_page = AsyncMock(return_value=page)

    with pytest.raises(RuntimeError, match="изменил структуру страницы"):
        await quizlet_scraper.scrape_set_terms(session, "123456")
