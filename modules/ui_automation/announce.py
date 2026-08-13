from __future__ import annotations

from modules.ui_automation.domain import UIStep

# One shared source of the spoken/reply phrasing for both core/voice/pipeline.py
# (spoken *before* the action runs) and core/voice/web_pipeline.py (only
# available *after* the fact there, since that endpoint is a single
# request/response — see that module's docstring on why it can't do a true
# multi-turn "announce, then act"). Keeping this in one place is what stops
# the two pipelines' wording from drifting apart.

_ROLE_WORDS: dict[str, dict[str, str]] = {
    "ru": {
        "push button": "кнопку",
        "toggle button": "кнопку",
        "menu item": "пункт меню",
        "check menu item": "пункт меню",
        "text": "поле",
        "entry": "поле",
        "check box": "флажок",
        "radio button": "переключатель",
        "combo box": "список",
        "list item": "элемент списка",
        "page tab": "вкладку",
        "link": "ссылку",
    },
    "uk": {
        "push button": "кнопку",
        "toggle button": "кнопку",
        "menu item": "пункт меню",
        "check menu item": "пункт меню",
        "text": "поле",
        "entry": "поле",
        "check box": "прапорець",
        "radio button": "перемикач",
        "combo box": "список",
        "list item": "елемент списку",
        "page tab": "вкладку",
        "link": "посилання",
    },
    "en": {
        "push button": "button",
        "toggle button": "button",
        "menu item": "menu item",
        "check menu item": "menu item",
        "text": "field",
        "entry": "field",
        "check box": "checkbox",
        "radio button": "radio button",
        "combo box": "dropdown",
        "list item": "list item",
        "page tab": "tab",
        "link": "link",
    },
}
_DEFAULT_ROLE_WORD = {"ru": "элемент", "uk": "елемент", "en": "element"}

_CLICK_TEMPLATE = {
    "ru": "Нажимаю {role} «{name}».",
    "uk": "Натискаю {role} «{name}».",
    "en": 'Clicking {role} "{name}".',
}
_TYPE_TEMPLATE = {
    "ru": "Печатаю «{text}».",
    "uk": "Друкую «{text}».",
    "en": 'Typing "{text}".',
}
_KEY_TEMPLATE = {
    "ru": "Нажимаю клавишу «{key}».",
    "uk": "Натискаю клавішу «{key}».",
    "en": 'Pressing "{key}".',
}


def describe_step(step: UIStep, language: str) -> str:
    if step.action == "click":
        assert step.element is not None
        role_words = _ROLE_WORDS.get(language, _ROLE_WORDS["ru"])
        role = role_words.get(step.element.role, _DEFAULT_ROLE_WORD.get(language, "элемент"))
        template = _CLICK_TEMPLATE.get(language, _CLICK_TEMPLATE["ru"])
        return template.format(role=role, name=step.element.name)
    if step.action == "type_text":
        template = _TYPE_TEMPLATE.get(language, _TYPE_TEMPLATE["ru"])
        return template.format(text=step.text)
    template = _KEY_TEMPLATE.get(language, _KEY_TEMPLATE["ru"])
    return template.format(key=step.key)


def describe_steps(steps: list[UIStep], language: str) -> str:
    return " ".join(describe_step(step, language) for step in steps)
