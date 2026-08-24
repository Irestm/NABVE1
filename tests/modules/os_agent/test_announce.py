from __future__ import annotations

from modules.os_agent import announce
from modules.ui_automation.domain import UIElement, UIStep


def test_mode_started_text_defaults_to_russian_for_unknown_language() -> None:
    assert announce.mode_started_text("fr") == announce.mode_started_text("ru")


def test_mode_started_text_supports_english() -> None:
    assert announce.mode_started_text("en") != announce.mode_started_text("ru")


def test_queue_summary_numbers_each_step() -> None:
    steps = [
        UIStep(action="click", element=UIElement(index=0, role="page tab", name="Настройки", bbox=(0, 0, 1, 1))),
        UIStep(action="type_text", text="привет"),
    ]
    text = announce.queue_summary(steps, "ru")
    assert text.startswith("1.")
    assert "2." in text
    assert "привет" in text


def test_queue_summary_prefixes_step_limit_notice() -> None:
    steps = [UIStep(action="press_key", key="Enter")]
    text = announce.queue_summary(steps, "ru", step_limit_reached=True)
    assert text.startswith(announce._STEP_LIMIT_PREFIX["ru"])
