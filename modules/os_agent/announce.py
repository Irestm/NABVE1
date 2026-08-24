from __future__ import annotations

from modules.ui_automation.announce import describe_step
from modules.ui_automation.domain import UIStep

# Fixed voice-response strings for modules/os_agent — same ru/uk/en shape as
# modules/ui_automation/announce.py (which describe_step is reused from
# below), NOT modules/board_games/announce.py's Russian-only precedent: this
# is product-facing TTS output, driven by core/voice/pipeline.py's
# response_language (which can differ from Russian when the user configured
# response_language_override), unrelated to this assistant session's own
# separate "reply to the user only in Russian" rule.

_MODE_STARTED = {
    "ru": "Режим агента включён. Какую задачу выполнить?",
    "uk": "Режим агента увімкнено. Яке завдання виконати?",
    "en": "Agent mode is on. What's the task?",
}
_MODE_STOPPED = {
    "ru": "Режим агента выключен.",
    "uk": "Режим агента вимкнено.",
    "en": "Agent mode is off.",
}
_NO_KEY_REFUSAL = {
    "ru": "Нужен подключённый ключ Gemini или Claude в настройках, чтобы включить режим агента.",
    "uk": "Потрібен підключений ключ Gemini або Claude в налаштуваннях, щоб увімкнути режим агента.",
    "en": "Agent mode needs a configured Gemini or Claude key in Settings.",
}
_STUCK_PREFIX = {
    "ru": "Не смог продолжить: ",
    "uk": "Не зміг продовжити: ",
    "en": "Couldn't continue: ",
}
_THROTTLED = {
    "ru": "Лимит запросов к ИИ исчерпан, останавливаюсь.",
    "uk": "Ліміт запитів до ШІ вичерпано, зупиняюся.",
    "en": "AI request limit reached, stopping here.",
}
_STEP_LIMIT_PREFIX = {
    "ru": "Достигнут лимит шагов. Вот что успел спланировать:",
    "uk": "Досягнуто ліміту кроків. Ось що встиг спланувати:",
    "en": "Reached the step limit. Here's what got planned so far:",
}
_CONFIRM_QUESTION = {
    "ru": "Выполнить эти действия?",
    "uk": "Виконати ці дії?",
    "en": "Run these actions?",
}
_CANCELLED = {
    "ru": "Отменено, ничего не выполнено.",
    "uk": "Скасовано, нічого не виконано.",
    "en": "Cancelled, nothing was run.",
}
_EXPLAIN_OFFER = {
    "ru": "Объяснить, почему я выбрал такие шаги?",
    "uk": "Пояснити, чому я обрав такі кроки?",
    "en": "Want me to explain why I chose these steps?",
}


def _pick(table: dict[str, str], language: str) -> str:
    return table.get(language, table["ru"])


def mode_started_text(language: str) -> str:
    return _pick(_MODE_STARTED, language)


def mode_stopped_text(language: str) -> str:
    return _pick(_MODE_STOPPED, language)


def no_key_refusal_text(language: str) -> str:
    return _pick(_NO_KEY_REFUSAL, language)


def stuck_text(reason: str, language: str) -> str:
    return _pick(_STUCK_PREFIX, language) + reason


def throttled_text(language: str) -> str:
    return _pick(_THROTTLED, language)


def confirm_question_text(language: str) -> str:
    return _pick(_CONFIRM_QUESTION, language)


def cancelled_text(language: str) -> str:
    return _pick(_CANCELLED, language)


def explain_offer_text(language: str) -> str:
    return _pick(_EXPLAIN_OFFER, language)


def queue_summary(steps: list[UIStep], language: str, step_limit_reached: bool = False) -> str:
    """Numbered spoken list of queued (not-yet-applied) actions, reusing
    modules.ui_automation.announce.describe_step per entry so the wording of
    an individual click/type_text/press_key never drifts between the
    single-shot ui_action flow and this one."""
    prefix = _pick(_STEP_LIMIT_PREFIX, language) + " " if step_limit_reached else ""
    numbered = " ".join(f"{i}. {describe_step(step, language)}" for i, step in enumerate(steps, start=1))
    return prefix + numbered
