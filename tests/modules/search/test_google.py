from __future__ import annotations

from modules.search.google import build_summary


def test_build_summary_returns_placeholder_for_no_results() -> None:
    assert build_summary([]) == "No results found."


def test_build_summary_includes_snippet_when_present() -> None:
    results = [{"title": "Python", "url": "https://python.org", "snippet": "Official site"}]

    assert build_summary(results) == "1. Python. Official site"


def test_build_summary_omits_snippet_when_empty() -> None:
    results = [{"title": "Python", "url": "https://python.org", "snippet": ""}]

    assert build_summary(results) == "1. Python."


def test_build_summary_numbers_multiple_results_in_order() -> None:
    results = [
        {"title": "First", "url": "https://a.example", "snippet": ""},
        {"title": "Second", "url": "https://b.example", "snippet": "details"},
    ]

    assert build_summary(results) == "1. First.\n2. Second. details"
