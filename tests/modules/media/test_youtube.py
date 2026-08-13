from __future__ import annotations

from modules.media.youtube import build_search_url


def test_builds_a_search_results_url() -> None:
    url = build_search_url("queen bohemian rhapsody")
    assert url.startswith("https://www.youtube.com/results?search_query=")
    assert "queen" in url


def test_url_encodes_special_characters() -> None:
    url = build_search_url("тест & музыка")
    assert " " not in url
    assert "&" not in url.split("search_query=")[1]
