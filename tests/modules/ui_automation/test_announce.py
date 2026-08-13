from __future__ import annotations

from modules.ui_automation.announce import describe_step, describe_steps
from modules.ui_automation.domain import UIElement, UIStep


def test_describe_click_step_names_role_and_label_ru() -> None:
    element = UIElement(index=0, role="push button", name="Сохранить", bbox=(0, 0, 10, 10))
    text = describe_step(UIStep(action="click", element=element), "ru")
    assert text == "Нажимаю кнопку «Сохранить»."


def test_describe_click_step_unknown_role_falls_back_to_generic_word() -> None:
    element = UIElement(index=0, role="some obscure role", name="X", bbox=(0, 0, 10, 10))
    text = describe_step(UIStep(action="click", element=element), "ru")
    assert text == "Нажимаю элемент «X»."


def test_describe_type_text_step_ru() -> None:
    text = describe_step(UIStep(action="type_text", text="привет мир"), "ru")
    assert text == "Печатаю «привет мир»."


def test_describe_press_key_step_ru() -> None:
    text = describe_step(UIStep(action="press_key", key="Enter"), "ru")
    assert text == "Нажимаю клавишу «Enter»."


def test_describe_click_step_en() -> None:
    element = UIElement(index=0, role="link", name="Trends", bbox=(0, 0, 10, 10))
    text = describe_step(UIStep(action="click", element=element), "en")
    assert text == 'Clicking link "Trends".'


def test_describe_steps_joins_multiple_steps() -> None:
    steps = [
        UIStep(action="click", element=UIElement(0, "entry", "Поиск", (0, 0, 10, 10))),
        UIStep(action="type_text", text="котики"),
        UIStep(action="press_key", key="Enter"),
    ]
    text = describe_steps(steps, "ru")
    assert text == "Нажимаю поле «Поиск». Печатаю «котики». Нажимаю клавишу «Enter»."


def test_describe_steps_unknown_language_falls_back_to_ru() -> None:
    element = UIElement(index=0, role="push button", name="OK", bbox=(0, 0, 10, 10))
    text = describe_step(UIStep(action="click", element=element), "fr")
    assert text == "Нажимаю кнопку «OK»."
