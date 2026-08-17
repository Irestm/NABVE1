from __future__ import annotations

import asyncio

import pytest

from modules.figma_control import dispatcher, screen_fallback
from modules.figma_control.command_parser import ParsedFigmaCommand, session_state
from modules.figma_control.ws_server import FigmaPluginUnavailableError


class FakeWsServer:
    def __init__(self, *, connected: bool, response: dict | None = None, raises: Exception | None = None) -> None:
        self.is_plugin_connected = connected
        self._response = response
        self._raises = raises
        self.sent: list[tuple[str, dict]] = []

    async def send_command(self, action: str, params: dict) -> dict:
        self.sent.append((action, params))
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response


@pytest.fixture(autouse=True)
def _reset_session_state():
    session_state.last_selected_layer = None
    yield
    session_state.last_selected_layer = None


def _run(text: str) -> str:
    return asyncio.run(dispatcher.process_figma_command(text))


def test_unparseable_text_reports_could_not_understand(monkeypatch):
    async def fake_parse(_text):
        return None

    monkeypatch.setattr(dispatcher.command_parser, "parse_command", fake_parse)
    assert _run("расскажи анекдот") == "Не поняла, что нужно сделать в Figma."


def _patch_parse(monkeypatch, action: str, params: dict) -> None:
    async def fake_parse(_text):
        return ParsedFigmaCommand(action=action, params=params)

    monkeypatch.setattr(dispatcher.command_parser, "parse_command", fake_parse)


def test_plugin_success_returns_plugin_message_and_updates_session(monkeypatch):
    _patch_parse(monkeypatch, "select_layer", {"layer_name": "Кнопка"})
    fake_server = FakeWsServer(
        connected=True, response={"status": "success", "message": "Слой выделен.", "result": {"name": "Кнопка"}}
    )
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)

    result = _run("выдели слой Кнопка")

    assert result == "Слой выделен."
    assert fake_server.sent == [("select_layer", {"layer_name": "Кнопка"})]
    assert session_state.last_selected_layer == "Кнопка"


def test_plugin_error_status_is_returned_without_fallback(monkeypatch):
    _patch_parse(monkeypatch, "select_layer", {"layer_name": "Нет такого"})
    fake_server = FakeWsServer(connected=True, response={"status": "error", "message": "Слой не найден."})
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)

    fallback_calls = []
    monkeypatch.setattr(
        dispatcher.screen_fallback, "execute", lambda action, params: fallback_calls.append((action, params))
    )

    result = _run("выдели слой Нет такого")

    assert result == "Слой не найден."
    assert fallback_calls == []


def test_plugin_unsupported_status_falls_back(monkeypatch):
    _patch_parse(monkeypatch, "undo", {})
    fake_server = FakeWsServer(connected=True, response={"status": "unsupported", "message": ""})
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)
    monkeypatch.setattr(dispatcher.screen_fallback, "execute", lambda action, params: "Отменено через управление экраном.")

    assert _run("отмени") == "Отменено через управление экраном."


def test_plugin_not_connected_goes_straight_to_fallback(monkeypatch):
    _patch_parse(monkeypatch, "group_selection", {})
    fake_server = FakeWsServer(connected=False)
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)
    monkeypatch.setattr(
        dispatcher.screen_fallback, "execute", lambda action, params: "Слои сгруппированы через управление экраном."
    )

    assert _run("сгруппируй") == "Слои сгруппированы через управление экраном."
    assert fake_server.sent == []


def test_plugin_unreachable_mid_send_falls_back(monkeypatch):
    _patch_parse(monkeypatch, "undo", {})
    fake_server = FakeWsServer(connected=True, raises=FigmaPluginUnavailableError("gone"))
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)
    monkeypatch.setattr(dispatcher.screen_fallback, "execute", lambda action, params: "Отменено через управление экраном.")

    assert _run("отмени") == "Отменено через управление экраном."


def test_fallback_refuses_when_figma_not_focused(monkeypatch):
    _patch_parse(monkeypatch, "create_rectangle", {"width": 10, "height": 10})
    monkeypatch.setattr(dispatcher, "figma_ws_server", FakeWsServer(connected=False))

    def _raise(_action, _params):
        raise screen_fallback.FigmaNotFocusedError("Active window is 'Chrome', not Figma")

    monkeypatch.setattr(dispatcher.screen_fallback, "execute", _raise)

    assert _run("создай прямоугольник 10 на 10") == "Не выполняю: активное окно сейчас не Figma."


def test_fallback_reports_unsupported_action(monkeypatch):
    _patch_parse(monkeypatch, "resize_layer", {"layer_name": "Кнопка", "width": 10, "height": 10})
    monkeypatch.setattr(dispatcher, "figma_ws_server", FakeWsServer(connected=False))

    def _raise(_action, _params):
        raise screen_fallback.FallbackActionUnsupportedError("no handler")

    monkeypatch.setattr(dispatcher.screen_fallback, "execute", _raise)

    assert _run("измени размер слоя Кнопка на 10 на 10") == "Не могу выполнить эту команду в Figma."


def test_delete_layer_clears_matching_last_selected_layer(monkeypatch):
    session_state.last_selected_layer = "Кнопка"
    _patch_parse(monkeypatch, "delete_layer", {"layer_name": "Кнопка"})
    fake_server = FakeWsServer(connected=True, response={"status": "success", "message": "Слой удалён."})
    monkeypatch.setattr(dispatcher, "figma_ws_server", fake_server)

    _run("удали слой Кнопка")

    assert session_state.last_selected_layer is None
