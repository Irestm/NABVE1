from __future__ import annotations

import httpx

from modules.youtube_control.domain import VideoResult

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_REQUEST_TIMEOUT_SECONDS = 10.0
SEARCH_COST_UNITS = 100


class YouTubeApiError(RuntimeError):
    pass


async def search_video(api_key: str, query: str) -> VideoResult | None:
    params = {
        "key": api_key,
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": 1,
    }
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(_SEARCH_URL, params=params)
    if response.status_code == 403:
        raise YouTubeApiError("YouTube API отказала в доступе — неверный ключ или дневная квота исчерпана.")
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        return None
    item = items[0]
    return VideoResult(video_id=item["id"]["videoId"], title=item["snippet"]["title"])
