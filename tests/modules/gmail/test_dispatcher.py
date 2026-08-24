from __future__ import annotations

import pytest

from modules.gmail import command_parser, dispatcher
from modules.gmail.command_parser import ParsedGmailCommand


class _FakeCreds:
    pass


@pytest.mark.asyncio
async def test_process_returns_not_understood_when_parser_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)

    result = await dispatcher.process_gmail_command("расскажи анекдот")

    assert result == "Не понял, что нужно сделать с почтой."


@pytest.mark.asyncio
async def test_process_returns_not_configured_message_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="list_recent_emails", params={})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(
        dispatcher.gmail_client, "ensure_credentials", lambda: (_ for _ in ()).throw(RuntimeError("not set up"))
    )

    result = await dispatcher.process_gmail_command("покажи последние письма")

    assert "python -m modules.gmail.login" in result


@pytest.mark.asyncio
async def test_process_list_recent_emails_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="list_recent_emails", params={"count": 2})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(dispatcher.gmail_client, "ensure_credentials", lambda: _FakeCreds())
    monkeypatch.setattr(dispatcher.gmail_client, "build_service", lambda creds: "fake-service")

    captured: dict[str, object] = {}

    def fake_search_messages(service, query, max_results):
        captured["service"] = service
        captured["query"] = query
        captured["max_results"] = max_results
        return [
            {"id": "m1", "from_email": "a@x.com", "from_name": "A", "subject": "Hi", "snippet": "hello"},
        ]

    monkeypatch.setattr(dispatcher.gmail_client, "search_messages", fake_search_messages)

    result = await dispatcher.process_gmail_command("покажи последние 2 письма")

    assert captured == {"service": "fake-service", "query": "in:inbox", "max_results": 2}
    assert "Hi" in result
    assert "hello" in result


@pytest.mark.asyncio
async def test_process_read_email_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="read_email", params={"sender": "boss"})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(dispatcher.gmail_client, "ensure_credentials", lambda: _FakeCreds())
    monkeypatch.setattr(dispatcher.gmail_client, "build_service", lambda creds: "fake-service")
    monkeypatch.setattr(
        dispatcher.gmail_client,
        "search_messages",
        lambda service, query, max_results: [
            {"id": "m1", "from_email": "boss@x.com", "from_name": "Boss", "subject": "Meeting", "snippet": "..."}
        ],
    )
    monkeypatch.setattr(dispatcher.gmail_client, "get_message_body", lambda service, message_id: "Full body text")

    result = await dispatcher.process_gmail_command("прочитай последнее письмо от boss")

    assert "Boss" in result
    assert "Meeting" in result
    assert "Full body text" in result


@pytest.mark.asyncio
async def test_process_read_email_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="read_email", params={"sender": "nobody"})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(dispatcher.gmail_client, "ensure_credentials", lambda: _FakeCreds())
    monkeypatch.setattr(dispatcher.gmail_client, "build_service", lambda creds: "fake-service")
    monkeypatch.setattr(dispatcher.gmail_client, "search_messages", lambda service, query, max_results: [])

    result = await dispatcher.process_gmail_command("прочитай последнее письмо от nobody")

    assert result == "Подходящее письмо не найдено."


@pytest.mark.asyncio
async def test_process_search_emails_empty_query_returns_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="search_emails", params={"query": ""})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(dispatcher.gmail_client, "ensure_credentials", lambda: _FakeCreds())
    monkeypatch.setattr(dispatcher.gmail_client, "build_service", lambda creds: "fake-service")

    result = await dispatcher.process_gmail_command("найди письма")

    assert result == "Не понял, что искать в почте."


@pytest.mark.asyncio
async def test_process_swallows_unexpected_exception_and_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse(text: str) -> ParsedGmailCommand:
        return ParsedGmailCommand(action="list_recent_emails", params={})

    monkeypatch.setattr(command_parser, "parse_command", fake_parse)
    monkeypatch.setattr(dispatcher.gmail_client, "ensure_credentials", lambda: _FakeCreds())

    def raise_error(creds):
        raise ConnectionError("network down")

    monkeypatch.setattr(dispatcher.gmail_client, "build_service", raise_error)

    result = await dispatcher.process_gmail_command("покажи последние письма")

    assert result == dispatcher._UNAVAILABLE_MESSAGE
