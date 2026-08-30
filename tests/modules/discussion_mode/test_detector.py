from __future__ import annotations

import pytest

from modules.discussion_mode import detector
from modules.discussion_mode.config import DEFAULT_ENTER_PHRASES, DEFAULT_EXIT_PHRASES


def test_enter_phrases_include_defaults_and_custom() -> None:
    assert detector.enter_phrases(None) == DEFAULT_ENTER_PHRASES
    assert detector.enter_phrases("го дискутировать")[-1] == "го дискутировать"


def test_exit_phrases_include_defaults_and_custom() -> None:
    assert detector.exit_phrases(None) == DEFAULT_EXIT_PHRASES
    assert "стоп дискуссия" in detector.exit_phrases("стоп дискуссия")


@pytest.mark.parametrize(
    "text",
    ["выйди из режима дискуссии", "хватит слушать", "прекрати дискуссию", "ну всё, закончи дискуссию"],
)
def test_is_exit_phrase_true(text: str) -> None:
    assert detector.is_exit_phrase(text) is True


def test_is_exit_phrase_respects_custom() -> None:
    assert detector.is_exit_phrase("отбой джарвис", "отбой джарвис") is True
    assert detector.is_exit_phrase("отбой джарвис") is False


def test_opinion_request_requires_lead_in_and_name() -> None:
    assert detector.is_opinion_request("что думаешь, джарвис?", "джарвис") is True
    assert detector.is_opinion_request("джарвис, твоё мнение какое?", "джарвис") is True
    # lead-in but no assistant name -> two humans talking to each other
    assert detector.is_opinion_request("а ты что думаешь по этому поводу", "джарвис") is False
    # name but no lead-in
    assert detector.is_opinion_request("джарвис, включи музыку", "джарвис") is False


def test_opinion_request_without_configured_name_only_needs_lead_in() -> None:
    assert detector.is_opinion_request("что думаешь про это", None) is True
    assert detector.is_opinion_request("просто болтаем дальше", None) is False
