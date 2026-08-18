from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.quizlet_clone import quizlet_auth
from modules.quizlet_clone.quizlet_auth import QuizletSession


@pytest.mark.asyncio
async def test_is_logged_in_false_when_never_opened() -> None:
    session = QuizletSession()
    assert await session.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_true_when_no_guest_marker_present() -> None:
    session = QuizletSession()
    session._context = MagicMock()
    page = MagicMock(url="https://quizlet.com/latest")
    page.locator.return_value.inner_text = AsyncMock(return_value="Мои наборы: Испанский, Немецкий")
    session._ensure_page = AsyncMock(return_value=page)

    assert await session.is_logged_in() is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_guest_marker_present() -> None:
    session = QuizletSession()
    session._context = MagicMock()
    page = MagicMock(url="https://quizlet.com/latest")
    page.locator.return_value.inner_text = AsyncMock(return_value="Войти  Зарегистрироваться")
    session._ensure_page = AsyncMock(return_value=page)

    assert await session.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_defaults_to_false_on_read_error() -> None:
    session = QuizletSession()
    session._context = MagicMock()
    page = MagicMock(url="https://quizlet.com/latest")
    page.locator.return_value.inner_text = AsyncMock(side_effect=RuntimeError("boom"))
    session._ensure_page = AsyncMock(return_value=page)

    assert await session.is_logged_in() is False


@pytest.mark.asyncio
async def test_ensure_page_relaunches_when_the_existing_context_was_closed_externally(
    tmp_path, monkeypatch
) -> None:
    # Simulates the user (or an OS sleep/crash) closing the actual browser
    # window between requests while this long-lived session object still
    # thinks it's alive — the fix in _ensure_page must detect that, discard
    # the stale references, and relaunch instead of propagating the raw
    # Playwright error to every subsequent Quizlet action.
    monkeypatch.setattr(quizlet_auth, "PROFILE_DIR", tmp_path / "quizlet_profile")
    # Never actually spawn Xvfb from a unit test — virtual_display.get_display()
    # is exercised for real by tests/modules/ai_bridge/test_virtual_display.py.
    monkeypatch.setattr(quizlet_auth.virtual_display, "get_display", AsyncMock(return_value=None))

    session = QuizletSession()
    dead_context = MagicMock()
    dead_context.pages = []
    dead_context.new_page = AsyncMock(
        side_effect=RuntimeError("Target page, context or browser has been closed")
    )
    session._context = dead_context
    old_playwright = MagicMock(stop=AsyncMock())
    session._playwright = old_playwright

    fresh_page = MagicMock()
    fresh_context = MagicMock()
    fresh_context.pages = []
    fresh_context.new_page = AsyncMock(return_value=fresh_page)
    fresh_context.add_init_script = AsyncMock()

    fake_browser_type = MagicMock()
    fake_browser_type.launch_persistent_context = AsyncMock(return_value=fresh_context)
    monkeypatch.setattr(quizlet_auth, "resolve_browser_launcher", lambda _pw: (fake_browser_type, {}))

    fake_playwright_instance = MagicMock()

    class _FakeAsyncPlaywright:
        async def start(self):
            return fake_playwright_instance

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakeAsyncPlaywright())

    page = await session._ensure_page()

    assert page is fresh_page
    assert session._context is fresh_context
    old_playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_tears_down_context_and_playwright() -> None:
    session = QuizletSession()
    session._context = MagicMock(close=AsyncMock())
    session._playwright = MagicMock(stop=AsyncMock())

    await session.close()

    assert session._context is None
    assert session._playwright is None


@pytest.mark.asyncio
async def test_logout_closes_session_and_wipes_profile_dir(tmp_path, monkeypatch) -> None:
    profile_dir = tmp_path / "quizlet_profile"
    profile_dir.mkdir()
    (profile_dir / "cookie_store").write_text("fake session data")
    monkeypatch.setattr(quizlet_auth, "PROFILE_DIR", profile_dir)

    fake_session = MagicMock(close=AsyncMock())
    monkeypatch.setattr(quizlet_auth, "get_session", lambda: fake_session)

    await quizlet_auth.logout()

    fake_session.close.assert_awaited_once()
    assert not profile_dir.exists()


@pytest.mark.asyncio
async def test_logout_is_safe_when_profile_dir_never_existed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(quizlet_auth, "PROFILE_DIR", tmp_path / "never_launched")
    fake_session = MagicMock(close=AsyncMock())
    monkeypatch.setattr(quizlet_auth, "get_session", lambda: fake_session)

    await quizlet_auth.logout()  # should not raise
