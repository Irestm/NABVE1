from __future__ import annotations

from core.logger import get_logger
from core.models import GENERIC_EXECUTED_MESSAGE, CommandResponse, CommandStatus
from core.voice import gender as gender_module

logger = get_logger(__name__)

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

_NOT_UNDERSTOOD: dict[str, dict[str, str]] = {
    "ru": {"male": "Не понял команду.", "female": "Не поняла команду."},
    "uk": {"male": "Не зрозумів команду.", "female": "Не зрозуміла команду."},
    "en": {"male": "I didn't understand that command.", "female": "I didn't understand that command."},
}

# Spoken before the window actually disappears/reappears (see
# core/voice/pipeline.py._wait_for_wake_or_pause's tray_hide/tray_show
# branches) - kept deliberately short since this fires every time the
# tray-hide phrase is used, not just once.
_TRAY_HIDE_ACK: dict[str, str] = {
    "ru": "Хорошо, ухожу в фон.",
    "uk": "Добре, йду у фон.",
    "en": "Okay, going to the background.",
}
_TRAY_SHOW_ACK: dict[str, str] = {
    "ru": "Возвращаюсь.",
    "uk": "Повертаюся.",
    "en": "Coming back.",
}


def localize_response(response: CommandResponse, language: str) -> str:
    templates = _TEMPLATES.get(language, _TEMPLATES["en"])
    # A handler that actually has something to say (see CommandDispatcher.
    # _execute) put it in response.message already, in the language the
    # assistant is answering in — speak that verbatim instead of the generic
    # per-status template, which would otherwise silently discard it (e.g. a
    # web_search result summary) and always say "Готово."/"Done." instead.
    if response.status == CommandStatus.EXECUTED and response.message != GENERIC_EXECUTED_MESSAGE:
        return response.message
    return templates.get(response.status, response.message)


def not_understood(language: str) -> str:
    logger.info("Speaking the not-understood fallback (language=%s)", language)
    variants = _NOT_UNDERSTOOD.get(language, _NOT_UNDERSTOOD["en"])
    return gender_module.pick(variants["male"], variants["female"])


def tray_hide_ack(language: str) -> str:
    return _TRAY_HIDE_ACK.get(language, _TRAY_HIDE_ACK["en"])


def tray_show_ack(language: str) -> str:
    return _TRAY_SHOW_ACK.get(language, _TRAY_SHOW_ACK["en"])
