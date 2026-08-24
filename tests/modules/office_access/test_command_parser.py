from __future__ import annotations

import pytest

from modules.office_access import command_parser


@pytest.mark.asyncio
async def test_open_database() -> None:
    parsed = await command_parser.parse_command("открой базу /home/user/contacts.odb")
    assert parsed == command_parser.ParsedAccessCommand(
        action="open_database", params={"path": "/home/user/contacts.odb"}
    )


@pytest.mark.asyncio
async def test_save_database() -> None:
    parsed = await command_parser.parse_command("сохрани базу данных")
    assert parsed == command_parser.ParsedAccessCommand(action="save_database", params={})


@pytest.mark.asyncio
async def test_close_database_with_save() -> None:
    parsed = await command_parser.parse_command("закрой базу с сохранением")
    assert parsed == command_parser.ParsedAccessCommand(action="close_database", params={"save": True})


@pytest.mark.asyncio
async def test_close_database_without_save() -> None:
    parsed = await command_parser.parse_command("закрой базу")
    assert parsed == command_parser.ParsedAccessCommand(action="close_database", params={"save": False})


@pytest.mark.asyncio
async def test_create_table() -> None:
    parsed = await command_parser.parse_command(
        "создай таблицу контакты с колонками имя текст, возраст число, день рождения дата"
    )
    assert parsed == command_parser.ParsedAccessCommand(
        action="create_table",
        params={
            "name": "контакты",
            "columns": [
                {"name": "имя", "type": "text"},
                {"name": "возраст", "type": "number"},
                {"name": "день рождения", "type": "date"},
            ],
        },
    )


@pytest.mark.asyncio
async def test_create_table_unknown_type_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("создай таблицу контакты с колонками имя штука_неведомая")
    assert parsed is None


@pytest.mark.asyncio
async def test_delete_table() -> None:
    parsed = await command_parser.parse_command("удали таблицу контакты")
    assert parsed == command_parser.ParsedAccessCommand(action="delete_table", params={"name": "контакты"})


@pytest.mark.asyncio
async def test_list_tables() -> None:
    parsed = await command_parser.parse_command("покажи таблицы")
    assert parsed == command_parser.ParsedAccessCommand(action="list_tables", params={})


@pytest.mark.asyncio
async def test_insert_row() -> None:
    parsed = await command_parser.parse_command("добавь в таблицу контакты имя равно Иван, возраст равно 30")
    assert parsed == command_parser.ParsedAccessCommand(
        action="insert_row", params={"table": "контакты", "values": {"имя": "иван", "возраст": 30}}
    )


@pytest.mark.asyncio
async def test_update_rows() -> None:
    parsed = await command_parser.parse_command(
        "измени в таблице контакты, где id равно 3, поставь возраст равно 31"
    )
    assert parsed == command_parser.ParsedAccessCommand(
        action="update_rows",
        params={"table": "контакты", "where_column": "id", "where_value": 3, "set": {"возраст": 31}},
    )


@pytest.mark.asyncio
async def test_delete_rows() -> None:
    parsed = await command_parser.parse_command("удали из таблицы контакты, где id равно 3")
    assert parsed == command_parser.ParsedAccessCommand(
        action="delete_rows", params={"table": "контакты", "where_column": "id", "where_value": 3}
    )


@pytest.mark.asyncio
async def test_list_rows_default_limit() -> None:
    parsed = await command_parser.parse_command("покажи записи из таблицы контакты")
    assert parsed == command_parser.ParsedAccessCommand(action="list_rows", params={"table": "контакты"})


@pytest.mark.asyncio
async def test_list_rows_with_limit() -> None:
    parsed = await command_parser.parse_command("покажи 5 записей из таблицы контакты")
    assert parsed == command_parser.ParsedAccessCommand(
        action="list_rows", params={"table": "контакты", "limit": 5}
    )


def test_parse_value_boolean_words() -> None:
    assert command_parser._parse_value("да") is True
    assert command_parser._parse_value("нет") is False


def test_parse_value_numeric() -> None:
    assert command_parser._parse_value("42") == 42
    assert command_parser._parse_value("3,5") == 3.5


def test_parse_value_text_fallback() -> None:
    assert command_parser._parse_value("Иван") == "Иван"


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
