from __future__ import annotations

import pytest

from modules.office_notes import command_parser


@pytest.mark.asyncio
async def test_open_notebook() -> None:
    parsed = await command_parser.parse_command("открой блокнот идеи")
    assert parsed == command_parser.ParsedNotesCommand(action="open_notebook", params={"name": "идеи"})


@pytest.mark.asyncio
async def test_create_notebook_same_phrasing() -> None:
    parsed = await command_parser.parse_command("создай блокнот проект")
    assert parsed == command_parser.ParsedNotesCommand(action="open_notebook", params={"name": "проект"})


@pytest.mark.asyncio
async def test_save_notebook() -> None:
    parsed = await command_parser.parse_command("сохрани блокнот")
    assert parsed == command_parser.ParsedNotesCommand(action="save_notebook", params={})


@pytest.mark.asyncio
async def test_close_notebook_with_save() -> None:
    parsed = await command_parser.parse_command("закрой блокнот с сохранением")
    assert parsed == command_parser.ParsedNotesCommand(action="close_notebook", params={"save": True})


@pytest.mark.asyncio
async def test_close_notebook_without_save() -> None:
    parsed = await command_parser.parse_command("закрой блокнот")
    assert parsed == command_parser.ParsedNotesCommand(action="close_notebook", params={"save": False})


@pytest.mark.asyncio
async def test_undo() -> None:
    parsed = await command_parser.parse_command("отмени")
    assert parsed == command_parser.ParsedNotesCommand(action="undo", params={})


@pytest.mark.asyncio
async def test_redo() -> None:
    parsed = await command_parser.parse_command("повтори")
    assert parsed == command_parser.ParsedNotesCommand(action="redo", params={})


@pytest.mark.asyncio
async def test_create_section() -> None:
    parsed = await command_parser.parse_command("создай раздел работа")
    assert parsed == command_parser.ParsedNotesCommand(action="create_section", params={"text": "работа"})


@pytest.mark.asyncio
async def test_create_page() -> None:
    parsed = await command_parser.parse_command("создай страницу встреча с клиентом")
    assert parsed == command_parser.ParsedNotesCommand(
        action="create_page", params={"text": "встреча с клиентом"}
    )


@pytest.mark.asyncio
async def test_write_text() -> None:
    parsed = await command_parser.parse_command("напиши купить молоко")
    assert parsed == command_parser.ParsedNotesCommand(action="write_text", params={"content": "купить молоко"})


@pytest.mark.asyncio
async def test_write_text_dopishi_phrasing() -> None:
    parsed = await command_parser.parse_command("допиши ещё одна мысль")
    assert parsed == command_parser.ParsedNotesCommand(action="write_text", params={"content": "ещё одна мысль"})


@pytest.mark.asyncio
async def test_list_structure() -> None:
    parsed = await command_parser.parse_command("покажи блокнот")
    assert parsed == command_parser.ParsedNotesCommand(action="list_structure", params={})


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
