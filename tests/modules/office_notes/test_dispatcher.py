from __future__ import annotations

import pytest

from core.config import NOTES_DIR
from modules.office_notes import command_parser, dispatcher
from modules.office_notes.command_parser import ParsedNotesCommand
from modules.office_writer.bridge_client import OfficeWriterUnavailableError


def test_notebook_path_sanitizes_unsafe_characters() -> None:
    # The real safety property: no path separator survives, so the result
    # is always a single filename component directly under NOTES_DIR — it
    # can't escape upward regardless of how many ".."/"/" the input has.
    path = dispatcher._notebook_path("../../etc/passwd")
    assert path.parent == NOTES_DIR
    assert "/" not in path.name


def test_notebook_path_keeps_cyrillic_and_spaces() -> None:
    path = dispatcher._notebook_path("мои идеи")
    assert path == NOTES_DIR / "мои идеи.odt"


def test_notebook_path_empty_name_falls_back() -> None:
    path = dispatcher._notebook_path("   ")
    assert path.stem == "блокнот"


@pytest.mark.parametrize(
    ("parsed", "expected_action", "expected_params"),
    [
        (ParsedNotesCommand("open_notebook", {"name": "идеи"}), "open_document", {"path": str(NOTES_DIR / "идеи.odt")}),
        (ParsedNotesCommand("save_notebook", {}), "save_document", {}),
        (ParsedNotesCommand("close_notebook", {"save": True}), "close_document", {"save": True}),
        (ParsedNotesCommand("undo", {}), "undo", {}),
        (ParsedNotesCommand("redo", {}), "redo", {}),
        (ParsedNotesCommand("create_section", {"text": "работа"}), "insert_heading", {"text": "работа", "level": 1}),
        (ParsedNotesCommand("create_page", {"text": "встреча"}), "insert_heading", {"text": "встреча", "level": 2}),
        (
            ParsedNotesCommand("write_text", {"content": "купить молоко"}),
            "insert_text",
            {"content": "купить молоко", "position": "end"},
        ),
        (ParsedNotesCommand("list_structure", {}), "list_headings", {}),
    ],
)
def test_to_writer_command_translates_every_known_action(parsed, expected_action, expected_params) -> None:
    action, params = dispatcher._to_writer_command(parsed)
    assert action == expected_action
    assert params == expected_params


def test_format_structure_empty() -> None:
    assert dispatcher._format_structure({"headings": []}) == "В блокноте пока нет разделов."


def test_format_structure_distinguishes_sections_and_pages() -> None:
    data = {"headings": [{"level": 1, "text": "Работа"}, {"level": 2, "text": "Задача 1"}]}
    result = dispatcher._format_structure(data)
    assert "Раздел: Работа" in result
    assert "Страница: Задача 1" in result


@pytest.mark.asyncio
async def test_process_returns_not_understood_when_parser_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    result = await dispatcher.process_notes_command("расскажи анекдот")

    assert result == "Не понял, что нужно сделать с блокнотом."


@pytest.mark.asyncio
async def test_process_open_notebook_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedNotesCommand:
        return ParsedNotesCommand(action="open_notebook", params={"name": "идеи"})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    async def fake_ensure_bridge_running() -> None:
        return None

    captured: dict[str, object] = {}

    async def fake_send_command(action, params=None, **kwargs):
        captured["action"] = action
        captured["params"] = params
        return {"status": "success", "message": "", "data": {}}

    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "ensure_bridge_running", fake_ensure_bridge_running)
    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "send_command", fake_send_command)

    result = await dispatcher.process_notes_command("открой блокнот идеи")

    assert result == "Блокнот открыт"
    assert captured["action"] == "open_document"
    assert captured["params"] == {"path": str(NOTES_DIR / "идеи.odt")}


@pytest.mark.asyncio
async def test_process_list_structure_speaks_sections_and_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedNotesCommand:
        return ParsedNotesCommand(action="list_structure", params={})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    async def fake_ensure_bridge_running() -> None:
        return None

    async def fake_send_command(action, params=None, **kwargs):
        return {
            "status": "success",
            "message": "",
            "data": {"headings": [{"level": 1, "text": "Работа"}, {"level": 2, "text": "Задача"}]},
        }

    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "ensure_bridge_running", fake_ensure_bridge_running)
    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "send_command", fake_send_command)

    result = await dispatcher.process_notes_command("покажи блокнот")

    assert "Раздел: Работа" in result
    assert "Страница: Задача" in result


@pytest.mark.asyncio
async def test_process_bridge_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedNotesCommand:
        return ParsedNotesCommand(action="save_notebook", params={})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    async def fake_ensure_bridge_running() -> None:
        raise OfficeWriterUnavailableError("bridge down")

    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "ensure_bridge_running", fake_ensure_bridge_running)

    result = await dispatcher.process_notes_command("сохрани блокнот")

    assert result == dispatcher._UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_process_bridge_rejects_command(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedNotesCommand:
        return ParsedNotesCommand(action="save_notebook", params={})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    async def fake_ensure_bridge_running() -> None:
        return None

    async def fake_send_command(action, params=None, **kwargs):
        return {"status": "error", "message": "Нет открытого документа Writer — сначала открой документ."}

    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "ensure_bridge_running", fake_ensure_bridge_running)
    monkeypatch.setattr(dispatcher.office_writer_bridge_client, "send_command", fake_send_command)

    result = await dispatcher.process_notes_command("сохрани блокнот")

    assert result == "Нет открытого документа Writer — сначала открой документ."
