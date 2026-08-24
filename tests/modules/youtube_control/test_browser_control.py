from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from modules.youtube_control import browser_control


class _FakeLocator:
    def __init__(self, title: str | None = "Video Title", raises_on_wait: bool = False) -> None:
        self._title = title
        self._raises_on_wait = raises_on_wait
        self.clicked = False

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def wait_for(self, timeout: int | None = None) -> None:
        if self._raises_on_wait:
            raise TimeoutError("no results found")

    async def get_attribute(self, name: str) -> str | None:
        return self._title

    async def click(self) -> None:
        self.clicked = True


class _FakePage:
    def __init__(self, locator: _FakeLocator | None = None) -> None:
        self.url = ""
        self.goto_calls: list[str] = []
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.click_calls: list[str] = []
        self._closed = False
        self._locator = locator or _FakeLocator()
        self._click_should_fail = False
        self.evaluate_return_value: Any = None

    def is_closed(self) -> bool:
        return self._closed

    async def goto(self, url: str, wait_until: str | None = None) -> None:
        self.goto_calls.append(url)
        self.url = url

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.evaluate_calls.append((script, arg))
        return self.evaluate_return_value

    async def click(self, selector: str, timeout: int | None = None) -> None:
        if self._click_should_fail:
            raise TimeoutError("selector not found")
        self.click_calls.append(selector)

    def locator(self, selector: str) -> _FakeLocator:
        return self._locator

    async def wait_for_url(self, pattern: str, timeout: int | None = None) -> None:
        self.url = "https://www.youtube.com/watch?v=abc123"


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]

    async def add_init_script(self, script: str) -> None:
        pass

    async def new_page(self) -> _FakePage:
        return self.pages[0]


class _FakeBrowserType:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context

    async def launch_persistent_context(self, **kwargs: Any) -> _FakeContext:
        return self._context


class _FakeAsyncPlaywrightCM:
    async def start(self) -> Any:
        return object()


@pytest.fixture(autouse=True)
def _fake_playwright_module(monkeypatch) -> None:
    fake_module = types.ModuleType("playwright.async_api")
    fake_module.async_playwright = lambda: _FakeAsyncPlaywrightCM()
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)


def _session_with_page(monkeypatch, page: _FakePage) -> browser_control.YouTubeBrowserSession:
    context = _FakeContext(page)
    browser_type = _FakeBrowserType(context)
    monkeypatch.setattr(browser_control, "resolve_browser_launcher", lambda playwright: (browser_type, {}))
    return browser_control.YouTubeBrowserSession()


async def test_open_video_navigates_to_the_watch_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    session = _session_with_page(monkeypatch, page)

    await session.open_video("abc123")

    assert page.goto_calls == ["https://www.youtube.com/watch?v=abc123"]


async def test_search_and_open_clicks_the_first_result_and_returns_its_title(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    locator = _FakeLocator(title="Найденное видео")
    page = _FakePage(locator=locator)
    session = _session_with_page(monkeypatch, page)

    title = await session.search_and_open("лоу фай бит")

    assert title == "Найденное видео"
    assert locator.clicked is True


async def test_search_and_open_raises_a_clear_error_when_nothing_found(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    locator = _FakeLocator(raises_on_wait=True)
    page = _FakePage(locator=locator)
    session = _session_with_page(monkeypatch, page)

    with pytest.raises(RuntimeError):
        await session.search_and_open("что-то несуществующее")


async def test_control_pause_evaluates_pause_on_the_video_element(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/watch?v=abc123"
    session = _session_with_page(monkeypatch, page)

    await session.control("pause", {})

    assert any("pause" in script for script, _ in page.evaluate_calls)


async def test_control_raises_when_no_video_is_open(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/"
    session = _session_with_page(monkeypatch, page)

    with pytest.raises(RuntimeError):
        await session.control("pause", {})


async def test_control_set_volume_passes_percent_argument(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/watch?v=abc123"
    session = _session_with_page(monkeypatch, page)

    await session.control("set_volume", {"percent": 42})

    assert page.evaluate_calls[-1][1] == 42


async def test_control_unknown_action_raises_value_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/watch?v=abc123"
    session = _session_with_page(monkeypatch, page)

    with pytest.raises(ValueError):
        await session.control("teleport", {})


# --- has_loaded_video / is_playing (used by modules.media_control) ---------


def test_has_loaded_video_false_before_any_page_exists() -> None:
    session = browser_control.YouTubeBrowserSession()

    assert session.has_loaded_video() is False


async def test_has_loaded_video_true_on_a_watch_page(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/watch?v=abc123"
    session = _session_with_page(monkeypatch, page)
    await session._ensure_page()

    assert session.has_loaded_video() is True


async def test_has_loaded_video_false_off_the_watch_page(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/"
    session = _session_with_page(monkeypatch, page)
    await session._ensure_page()

    assert session.has_loaded_video() is False


async def test_is_playing_false_when_nothing_loaded() -> None:
    session = browser_control.YouTubeBrowserSession()

    assert await session.is_playing() is False


async def test_is_playing_reflects_the_video_paused_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser_control, "_PROFILE_DIR", tmp_path)
    page = _FakePage()
    page.url = "https://www.youtube.com/watch?v=abc123"
    page.evaluate_return_value = False
    session = _session_with_page(monkeypatch, page)
    await session._ensure_page()

    assert await session.is_playing() is True

    page.evaluate_return_value = True
    assert await session.is_playing() is False


def test_module_level_has_loaded_video_false_without_a_session() -> None:
    assert browser_control.has_loaded_video() is False


async def test_module_level_is_playing_false_without_a_session() -> None:
    assert await browser_control.is_playing() is False
