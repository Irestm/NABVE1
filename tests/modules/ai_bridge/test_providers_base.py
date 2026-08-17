from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ai_bridge.providers.base import BrowserProviderAdapter


class _FakeAdapter(BrowserProviderAdapter):
    name = "fake"
    url = "https://example.com/app"
    profile_dirname = "fake"
    prompt_box_selectors = ("textarea", "[contenteditable='true']")
    response_block_selectors = (".response",)
    limit_markers = ("daily limit reached",)

    def _describe(self) -> str:
        return "Fake"


@pytest.mark.asyncio
async def test_is_logged_in_false_when_never_opened() -> None:
    adapter = _FakeAdapter()

    assert await adapter.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_true_when_no_guest_marker_present() -> None:
    adapter = _FakeAdapter()
    adapter._context = MagicMock()
    page = MagicMock(url=adapter.url)
    page.locator.return_value.inner_text = AsyncMock(return_value="Some normal page content")
    adapter._ensure_page = AsyncMock(return_value=page)

    assert await adapter.is_logged_in() is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_guest_marker_present() -> None:
    adapter = _FakeAdapter()
    adapter._context = MagicMock()
    page = MagicMock(url=adapter.url)
    page.locator.return_value.inner_text = AsyncMock(return_value="Please Sign in to continue")
    adapter._ensure_page = AsyncMock(return_value=page)

    assert await adapter.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_limit_reached_false_when_no_markers_configured() -> None:
    class _NoLimitAdapter(_FakeAdapter):
        limit_markers = ()

    adapter = _NoLimitAdapter()

    assert await adapter.is_limit_reached() is False


@pytest.mark.asyncio
async def test_is_limit_reached_true_when_marker_present() -> None:
    adapter = _FakeAdapter()
    page = MagicMock()
    page.locator.return_value.inner_text = AsyncMock(return_value="You have reached your Daily Limit Reached today")
    adapter._ensure_page = AsyncMock(return_value=page)

    assert await adapter.is_limit_reached() is True


@pytest.mark.asyncio
async def test_locate_prompt_box_raises_runtime_error_when_every_selector_fails() -> None:
    adapter = _FakeAdapter()
    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=RuntimeError("timeout"))

    with pytest.raises(RuntimeError, match="changed its layout"):
        await adapter._locate_prompt_box(page)


@pytest.mark.asyncio
async def test_locate_prompt_box_returns_locator_for_first_working_selector() -> None:
    adapter = _FakeAdapter()
    page = MagicMock()
    page.wait_for_selector = AsyncMock()
    sentinel_locator = MagicMock()
    page.locator.return_value.first = sentinel_locator

    result = await adapter._locate_prompt_box(page)

    page.wait_for_selector.assert_awaited_once()
    assert result is sentinel_locator


@pytest.mark.asyncio
async def test_close_resets_state_even_if_context_close_raises() -> None:
    adapter = _FakeAdapter()
    adapter._context = MagicMock(close=AsyncMock(side_effect=RuntimeError("already gone")))
    adapter._playwright = MagicMock(stop=AsyncMock())

    await adapter.close()

    assert adapter._context is None
    assert adapter._page is None
    assert adapter._playwright is None


@pytest.mark.asyncio
async def test_close_resets_state_even_if_playwright_stop_raises() -> None:
    adapter = _FakeAdapter()
    adapter._context = MagicMock(close=AsyncMock())
    adapter._playwright = MagicMock(stop=AsyncMock(side_effect=RuntimeError("already stopped")))

    await adapter.close()

    assert adapter._context is None
    assert adapter._playwright is None


@pytest.mark.asyncio
async def test_close_is_a_noop_when_nothing_was_ever_opened() -> None:
    adapter = _FakeAdapter()

    await adapter.close()
