"""Entry point for voice-driven Gmail reading (NABVE1's "Outlook" slice of
the office-suite task — see AGENT_NOTES.md: Gmail has no send/delete
scope, deliberately, so this module only ever lists/searches/reads, never
replies or deletes; modules/messaging already covers watch/notify for new
mail arriving from watched senders).

process_gmail_command(text) is the module's whole public surface: parse ->
run the matching Gmail API call (off the event loop, via asyncio.to_thread,
since the Google API client is synchronous) -> speak the result.
register_commands(dispatcher) wires exactly one command ("gmail_command", a
raw-text param) into the shared dispatcher, same one-generic-command
reasoning as this app's other voice-controlled modules.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.gmail import client as gmail_client
from modules.gmail import command_parser
from modules.gmail.command_parser import DEFAULT_COUNT, ParsedGmailCommand

logger = get_logger(__name__)

_NOT_CONFIGURED_MESSAGE = (
    "Gmail не подключён. Настрой переменные окружения ASSISTANT_GMAIL_CLIENT_ID/"
    "ASSISTANT_GMAIL_CLIENT_SECRET и выполни один раз: python -m modules.gmail.login"
)
_UNAVAILABLE_MESSAGE = "Не удалось подключиться к Gmail, попробуй ещё раз чуть позже."

# Voice read-aloud of an entire email body has to stop somewhere — this is
# generous enough for a normal message while keeping TTS from choking on a
# multi-page thread quote.
_MAX_SPOKEN_BODY_CHARS = 2000


def _build_list_query(params: dict[str, Any]) -> str:
    parts = ["in:inbox"]
    if params.get("unread_only"):
        parts.append("is:unread")
    return " ".join(parts)


def _build_read_query(params: dict[str, Any]) -> str:
    parts = []
    sender = params.get("sender")
    if sender:
        parts.append(f"from:{sender}")
    subject_contains = params.get("subject_contains")
    if subject_contains:
        parts.append(f"subject:{subject_contains}")
    return " ".join(parts) if parts else "in:inbox"


def _format_email_list(messages: list[dict[str, str]]) -> str:
    if not messages:
        return "Писем не найдено."
    lines = [
        f"{index}. От {message['from_name']}: {message['subject'] or '(без темы)'} — {message['snippet']}"
        for index, message in enumerate(messages, start=1)
    ]
    return f"Нашёл {len(messages)} писем. " + " ".join(lines)


def _format_email_body(message: dict[str, str], body: str) -> str:
    header = f"Письмо от {message['from_name']}, тема: {message['subject'] or 'без темы'}."
    truncated = body[:_MAX_SPOKEN_BODY_CHARS].strip()
    suffix = "" if len(body) <= _MAX_SPOKEN_BODY_CHARS else " Письмо длинное, прочитал начало."
    return f"{header} {truncated}{suffix}".strip()


def _execute(service: Any, action: str, params: dict[str, Any]) -> str:
    if action == "list_recent_emails":
        query = _build_list_query(params)
        count = int(params.get("count") or DEFAULT_COUNT)
        messages = gmail_client.search_messages(service, query, max_results=count)
        return _format_email_list(messages)

    if action == "search_emails":
        query = str(params.get("query") or "")
        if not query:
            return "Не понял, что искать в почте."
        count = int(params.get("count") or DEFAULT_COUNT)
        messages = gmail_client.search_messages(service, query, max_results=count)
        return _format_email_list(messages)

    if action == "read_email":
        query = _build_read_query(params)
        messages = gmail_client.search_messages(service, query, max_results=1)
        if not messages:
            return "Подходящее письмо не найдено."
        message = messages[0]
        body = gmail_client.get_message_body(service, message["id"])
        return _format_email_body(message, body)

    return "Неизвестное действие с почтой."


async def process_gmail_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. load/refresh stored OAuth credentials — a clear "not configured"
    message if modules/gmail/login.py's interactive helper was never run;
    3. run the matching read-only Gmail API call off the event loop;
    4. return a short Russian sentence for TTS describing what happened.
    Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать с почтой."

    try:
        creds = await asyncio.to_thread(gmail_client.ensure_credentials)
    except RuntimeError:
        return _NOT_CONFIGURED_MESSAGE
    except Exception:
        logger.exception("Gmail command '%s': failed to load credentials", parsed.action)
        return _UNAVAILABLE_MESSAGE

    try:
        service = await asyncio.to_thread(gmail_client.build_service, creds)
        return await asyncio.to_thread(_execute, service, parsed.action, parsed.params)
    except Exception:
        logger.exception("Gmail command '%s' failed", parsed.action)
        return _UNAVAILABLE_MESSAGE


async def _handle_gmail_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_gmail_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "gmail_command",
        _handle_gmail_command,
        dangerous=False,
        description=(
            "Чтение почты Gmail голосом: последние письма, непрочитанные письма, поиск писем по "
            "отправителю/теме/тексту, чтение содержимого письма. Только чтение — ответить или удалить "
            "письмо голосом нельзя (осознанное ограничение). Использовать при любом упоминании почты, "
            "Gmail, писем, входящих (text — полная исходная фраза пользователя)."
        ),
    )
