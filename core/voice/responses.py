from __future__ import annotations

from core.models import CommandResponse, CommandStatus

_TEMPLATES: dict[str, dict[CommandStatus, str]] = {
    "ru": {
        CommandStatus.EXECUTED: "Готово.",
        CommandStatus.CONFIRMATION_REQUIRED: "Требуется подтверждение. Скажите «да», чтобы продолжить.",
        CommandStatus.CANCELLED: "Отменено.",
        CommandStatus.FAILED: "Не удалось выполнить команду.",
    },
    "uk": {
        CommandStatus.EXECUTED: "Готово.",
        CommandStatus.CONFIRMATION_REQUIRED: "Потрібне підтвердження. Скажіть «так», щоб продовжити.",
        CommandStatus.CANCELLED: "Скасовано.",
        CommandStatus.FAILED: "Не вдалося виконати команду.",
    },
    "en": {
        CommandStatus.EXECUTED: "Done.",
        CommandStatus.CONFIRMATION_REQUIRED: "Confirmation required. Say 'yes' to proceed.",
        CommandStatus.CANCELLED: "Cancelled.",
        CommandStatus.FAILED: "The command could not be executed.",
    },
}

_NOT_UNDERSTOOD: dict[str, str] = {
    "ru": "Не поняла команду.",
    "uk": "Не зрозуміла команду.",
    "en": "I didn't understand that command.",
}


_GENERIC_EXECUTED_MESSAGE = "Command executed."


def localize_response(response: CommandResponse, language: str) -> str:
    templates = _TEMPLATES.get(language, _TEMPLATES["en"])
    # A handler that actually has something to say (see CommandDispatcher.
    # _execute) put it in response.message already, in the language the
    # assistant is answering in — speak that verbatim instead of the generic
    # per-status template, which would otherwise silently discard it (e.g. a
    # web_search result summary) and always say "Готово."/"Done." instead.
    if response.status == CommandStatus.EXECUTED and response.message != _GENERIC_EXECUTED_MESSAGE:
        return response.message
    return templates.get(response.status, response.message)


def not_understood(language: str) -> str:
    return _NOT_UNDERSTOOD.get(language, _NOT_UNDERSTOOD["en"])
