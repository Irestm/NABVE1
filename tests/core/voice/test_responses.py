from __future__ import annotations

from core.models import GENERIC_EXECUTED_MESSAGE, CommandResponse, CommandStatus
from core.voice.responses import localize_response, not_understood, tray_hide_ack, tray_show_ack


def _response(status: CommandStatus, message: str = GENERIC_EXECUTED_MESSAGE) -> CommandResponse:
    return CommandResponse(status=status, command="some_command", message=message)


def test_localize_response_uses_the_generic_template_for_executed() -> None:
    assert localize_response(_response(CommandStatus.EXECUTED), "ru") == "Готово."


def test_localize_response_speaks_a_custom_handler_message_verbatim() -> None:
    response = _response(CommandStatus.EXECUTED, message="Нашла три письма от Иры.")

    assert localize_response(response, "ru") == "Нашла три письма от Иры."


def test_localize_response_confirmation_required() -> None:
    text = localize_response(_response(CommandStatus.CONFIRMATION_REQUIRED), "ru")

    assert "подтверждение" in text


def test_localize_response_cancelled() -> None:
    assert localize_response(_response(CommandStatus.CANCELLED), "en") == "Cancelled."


def test_localize_response_failed() -> None:
    assert localize_response(_response(CommandStatus.FAILED), "uk") == "Не вдалося виконати команду."


def test_localize_response_falls_back_to_english_for_unknown_language() -> None:
    assert localize_response(_response(CommandStatus.EXECUTED), "fr") == "Done."


def test_not_understood_per_language() -> None:
    assert not_understood("ru") == "Не поняла команду."
    assert not_understood("en") == "I didn't understand that command."
    assert not_understood("fr") == "I didn't understand that command."


def test_tray_hide_and_show_ack_per_language() -> None:
    assert tray_hide_ack("ru") == "Хорошо, ухожу в фон."
    assert tray_show_ack("uk") == "Повертаюся."
    assert tray_hide_ack("fr") == "Okay, going to the background."
