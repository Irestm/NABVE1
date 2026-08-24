from __future__ import annotations

from modules.os_agent.safety import is_write_action
from modules.ui_automation.domain import UIElement, UIStep


def _element(role: str, name: str) -> UIElement:
    return UIElement(index=0, role=role, name=name, bbox=(0, 0, 10, 10))


def test_type_text_is_always_write() -> None:
    assert is_write_action(UIStep(action="type_text", text="hi")) is True


def test_press_key_enter_is_write() -> None:
    assert is_write_action(UIStep(action="press_key", key="Return")) is True


def test_press_key_tab_is_free() -> None:
    assert is_write_action(UIStep(action="press_key", key="Tab")) is False


def test_press_key_escape_is_free_case_insensitive() -> None:
    assert is_write_action(UIStep(action="press_key", key="ESCAPE")) is False


def test_click_nav_role_safe_name_is_free() -> None:
    step = UIStep(action="click", element=_element("page tab", "Настройки"))
    assert is_write_action(step) is False


def test_click_nav_role_but_commit_keyword_name_is_write() -> None:
    step = UIStep(action="click", element=_element("link", "Удалить аккаунт"))
    assert is_write_action(step) is True


def test_click_non_nav_role_is_write_even_with_safe_name() -> None:
    step = UIStep(action="click", element=_element("push button", "Дальше"))
    assert is_write_action(step) is True


def test_click_push_button_save_is_write() -> None:
    step = UIStep(action="click", element=_element("push button", "Сохранить"))
    assert is_write_action(step) is True


def test_click_english_commit_keyword_is_write() -> None:
    step = UIStep(action="click", element=_element("link", "Delete account"))
    assert is_write_action(step) is True


def test_click_with_no_element_is_write() -> None:
    assert is_write_action(UIStep(action="click", element=None)) is True
