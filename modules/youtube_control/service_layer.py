from __future__ import annotations

from core.logger import get_logger
from core.secret_store import get_secret
from modules.youtube_control import api_client, browser_control
from modules.youtube_control.domain import QuotaStatus
from modules.youtube_control.quota_tracker import QuotaTracker

logger = get_logger(__name__)

API_KEY_SECRET_NAME = "youtube_api_key"

_quota_tracker = QuotaTracker()


def quota_status() -> QuotaStatus:
    return _quota_tracker.status()


def _near_limit_warning_suffix() -> str:
    if not _quota_tracker.consume_near_limit_warning():
        return ""
    status = _quota_tracker.status()
    return f" Кстати, скоро закончится дневной лимит поиска на YouTube ({status.remaining_searches} поисков осталось)."


async def search_and_play(query: str) -> str:
    api_key = get_secret(API_KEY_SECRET_NAME)
    quota = _quota_tracker.status()
    result = None
    if api_key and not quota.exhausted:
        try:
            result = await api_client.search_video(api_key, query)
            _quota_tracker.record_usage(api_client.SEARCH_COST_UNITS)
        except api_client.YouTubeApiError:
            logger.exception("YouTube Data API search failed for %r, falling back to browser search", query)

    if result is not None:
        await browser_control.get_session().open_video(result.video_id)
        return f"Включаю на YouTube: {result.title}.{_near_limit_warning_suffix()}"

    title = await browser_control.get_session().search_and_open(query)
    return f"Включаю на YouTube: {title}.{_near_limit_warning_suffix()}"


async def pause() -> str:
    await browser_control.get_session().control("pause", {})
    return "Пауза."


async def resume() -> str:
    await browser_control.get_session().control("resume", {})
    return "Продолжаю."


async def next_video() -> str:
    await browser_control.get_session().control("next", {})
    return "Следующее видео."


async def seek(offset_seconds: int) -> str:
    await browser_control.get_session().control("seek", {"offset_seconds": offset_seconds})
    return "Перемотал вперёд." if offset_seconds >= 0 else "Перемотал назад."


async def set_volume(percent: int) -> str:
    await browser_control.get_session().control("set_volume", {"percent": percent})
    return f"Громкость {percent} процентов."


async def set_speed(rate: float) -> str:
    await browser_control.get_session().control("set_speed", {"rate": rate})
    return f"Скорость {rate}x."


async def has_session() -> bool:
    """Whether a video is loaded at all (playing or paused) — used by
    modules.media_control. Async for a uniform interface with
    modules.spotify_control.service_layer.has_session(), even though the
    underlying check itself is synchronous."""
    return browser_control.has_loaded_video()


async def is_active() -> bool:
    return await browser_control.is_playing()
