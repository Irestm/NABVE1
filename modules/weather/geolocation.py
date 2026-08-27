from __future__ import annotations

import httpx

from core.logger import get_logger

logger = get_logger(__name__)

_GEOLOCATION_URL = "https://ipwho.is/"
_REQUEST_TIMEOUT_SECONDS = 5.0


async def detect_city_from_ip() -> str | None:
    """Best-effort IP-based city guess for when the user doesn't name one
    and hasn't set modules/user_profile's CITY_KEY either - see
    modules/weather/service_layer.py's fallback chain. No API key needed
    (ipwho.is's free tier - tried ipapi.co first, but that one's free-tier
    rate limit was already exhausted from this machine's IP the moment
    this was written, so it never got a chance to answer). Silently
    returns None on any failure (offline, rate-limited, no city in the
    response, ...): this is the last, optional rung of that chain, not
    something that should ever surface a scary error of its own - a caller
    that gets None here just falls through to the existing "please name a
    city" clarifying question."""
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(_GEOLOCATION_URL)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success", True):
                logger.debug("IP geolocation for weather's default city failed: %s", payload.get("message"))
                return None
            city = payload.get("city")
    except Exception as exc:
        logger.debug("IP geolocation for weather's default city failed: %s", exc, exc_info=True)
        return None
    return city or None
