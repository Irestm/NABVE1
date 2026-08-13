from __future__ import annotations

from urllib.parse import quote_plus


def build_search_url(query: str) -> str:
    """A YouTube search-results URL for `query` — handed to
    core.os_adapter's open_application(target), same mechanism already used
    for steam:// URIs (see modules/app_catalog/steam.py): xdg-open/`start`
    both open an http(s):// URL in the default browser without any
    YouTube-specific code needed on our side."""
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
