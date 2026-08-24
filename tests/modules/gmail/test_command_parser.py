from __future__ import annotations

import pytest

from modules.gmail import command_parser


@pytest.mark.asyncio
async def test_list_recent_default() -> None:
    parsed = await command_parser.parse_command("покажи последние письма")
    assert parsed == command_parser.ParsedGmailCommand(action="list_recent_emails", params={})


@pytest.mark.asyncio
async def test_list_recent_with_count() -> None:
    parsed = await command_parser.parse_command("покажи последние 3 письма")
    assert parsed == command_parser.ParsedGmailCommand(action="list_recent_emails", params={"count": 3})


@pytest.mark.asyncio
async def test_list_unread() -> None:
    parsed = await command_parser.parse_command("покажи непрочитанные письма")
    assert parsed == command_parser.ParsedGmailCommand(action="list_recent_emails", params={"unread_only": True})


@pytest.mark.asyncio
async def test_new_mail_phrasing() -> None:
    parsed = await command_parser.parse_command("новые письма")
    assert parsed == command_parser.ParsedGmailCommand(action="list_recent_emails", params={})


@pytest.mark.asyncio
async def test_search_by_sender() -> None:
    parsed = await command_parser.parse_command("найди письма от Иван Иванов")
    assert parsed == command_parser.ParsedGmailCommand(
        action="search_emails", params={"query": "from:иван иванов"}
    )


@pytest.mark.asyncio
async def test_search_by_subject() -> None:
    parsed = await command_parser.parse_command("найди письма про счета")
    assert parsed == command_parser.ParsedGmailCommand(action="search_emails", params={"query": "счета"})


@pytest.mark.asyncio
async def test_search_generic() -> None:
    parsed = await command_parser.parse_command("найди письма отпуск")
    assert parsed == command_parser.ParsedGmailCommand(action="search_emails", params={"query": "отпуск"})


@pytest.mark.asyncio
async def test_read_email_from_sender() -> None:
    parsed = await command_parser.parse_command("прочитай последнее письмо от начальника")
    assert parsed == command_parser.ParsedGmailCommand(action="read_email", params={"sender": "начальника"})


@pytest.mark.asyncio
async def test_read_email_by_subject() -> None:
    parsed = await command_parser.parse_command("прочитай письмо про встречу")
    assert parsed == command_parser.ParsedGmailCommand(action="read_email", params={"subject_contains": "встречу"})


@pytest.mark.asyncio
async def test_read_email_no_filter() -> None:
    parsed = await command_parser.parse_command("прочитай последнее письмо")
    assert parsed == command_parser.ParsedGmailCommand(action="read_email", params={})


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
