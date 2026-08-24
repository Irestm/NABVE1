from __future__ import annotations

import asyncio
from typing import Any

from core.browser_automation import HIDE_WEBDRIVER_INIT_SCRIPT, resolve_browser_launcher
from core.config import DATA_DIR
from core.logger import get_logger

logger = get_logger(__name__)

_PROFILE_DIR = DATA_DIR / "browser_profiles" / "youtube_control"
_SEARCH_URL_TEMPLATE = "https://www.youtube.com/results?search_query={query}"
_NEXT_BUTTON_SELECTOR = ".ytp-next-button"
_SEARCH_RESULT_SELECTOR = "ytd-video-renderer a#video-title"


class YouTubeBrowserSession:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_page(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright не установлен. Установите: pip install playwright && playwright install firefox chromium"
            ) from exc

        if self._context is None:
            _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            browser_type, engine_kwargs = resolve_browser_launcher(self._playwright)
            self._context = await browser_type.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR),
                headless=False,
                viewport=None,
                **engine_kwargs,
            )
            await self._context.add_init_script(HIDE_WEBDRIVER_INIT_SCRIPT)
            logger.info("Launched persistent YouTube browser context at %s", _PROFILE_DIR)

        if self._page is None or self._page.is_closed():
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def open_video(self, video_id: str) -> None:
        async with self._lock:
            page = await self._ensure_page()
            await page.goto(f"https://www.youtube.com/watch?v={video_id}", wait_until="domcontentloaded")

    async def search_and_open(self, query: str) -> str:
        async with self._lock:
            page = await self._ensure_page()
            await page.goto(_SEARCH_URL_TEMPLATE.format(query=query), wait_until="domcontentloaded")
            link = page.locator(_SEARCH_RESULT_SELECTOR).first
            try:
                await link.wait_for(timeout=10_000)
            except Exception as exc:
                raise RuntimeError(f"Не нашёл на YouTube ничего по запросу «{query}».") from exc
            title = await link.get_attribute("title") or query
            await link.click()
            await page.wait_for_url("**/watch*", timeout=10_000)
            return title

    async def control(self, action: str, params: dict[str, Any]) -> None:
        async with self._lock:
            page = await self._ensure_page()
            if "watch" not in page.url:
                raise RuntimeError("Сейчас на YouTube не открыто видео для управления.")
            if action == "pause":
                await page.evaluate("document.querySelector('video')?.pause()")
            elif action == "resume":
                await page.evaluate("document.querySelector('video')?.play()")
            elif action == "next":
                try:
                    await page.click(_NEXT_BUTTON_SELECTOR, timeout=3_000)
                except Exception as exc:
                    raise RuntimeError("Кнопка «следующее видео» недоступна — нет очереди воспроизведения.") from exc
            elif action == "seek":
                await page.evaluate(
                    "(offset) => { const v = document.querySelector('video'); if (v) v.currentTime += offset; }",
                    params["offset_seconds"],
                )
            elif action == "set_volume":
                await page.evaluate(
                    "(percent) => { const v = document.querySelector('video'); if (v) v.volume = percent / 100; }",
                    params["percent"],
                )
            elif action == "set_speed":
                await page.evaluate(
                    "(rate) => { const v = document.querySelector('video'); if (v) v.playbackRate = rate; }",
                    params["rate"],
                )
            else:
                raise ValueError(f"Неизвестное действие управления YouTube: {action!r}")

    def has_loaded_video(self) -> bool:
        return self._page is not None and not self._page.is_closed() and "watch" in self._page.url

    async def is_playing(self) -> bool:
        if not self.has_loaded_video():
            return False
        try:
            paused = await self._page.evaluate("document.querySelector('video')?.paused ?? true")
        except Exception:
            return False
        return not paused


_session: YouTubeBrowserSession | None = None


def get_session() -> YouTubeBrowserSession:
    global _session
    if _session is None:
        _session = YouTubeBrowserSession()
    return _session


def has_loaded_video() -> bool:
    """Status-only check for modules.media_control — deliberately reads the
    module-level _session directly instead of going through get_session(),
    which would lazily launch a whole new browser context just to answer
    "is anything open" (always False for a session that doesn't exist
    yet)."""
    return _session is not None and _session.has_loaded_video()


async def is_playing() -> bool:
    if _session is None:
        return False
    return await _session.is_playing()
