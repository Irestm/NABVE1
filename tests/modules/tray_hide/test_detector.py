from __future__ import annotations

from modules.tray_hide import detector
from modules.tray_hide.config import DEFAULT_HIDE_PHRASES, DEFAULT_SHOW_PHRASES


def test_hide_phrases_returns_only_defaults_when_no_custom_phrase() -> None:
    assert detector.hide_phrases(None) == DEFAULT_HIDE_PHRASES


def test_hide_phrases_appends_custom_phrase() -> None:
    result = detector.hide_phrases("исчезни")
    assert result == (*DEFAULT_HIDE_PHRASES, "исчезни")


def test_show_phrases_returns_only_defaults_when_no_custom_phrase() -> None:
    assert detector.show_phrases(None) == DEFAULT_SHOW_PHRASES


def test_show_phrases_appends_custom_phrase() -> None:
    result = detector.show_phrases("появись")
    assert result == (*DEFAULT_SHOW_PHRASES, "появись")


def test_empty_custom_phrase_is_treated_as_unset() -> None:
    assert detector.hide_phrases("") == DEFAULT_HIDE_PHRASES
    assert detector.show_phrases("") == DEFAULT_SHOW_PHRASES
