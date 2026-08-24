"""Rule-based Russian voice -> Gmail read-only action parser.

Same shape as this app's office command_parser.py modules: cheap regex
patterns checked first, an AI-structuring pass as a fallback, scoped to this
module's own action vocabulary (KNOWN_ACTIONS). Deliberately read-only —
list/search/read only, no send/delete/modify — see modules/gmail/client.py's
SCOPES docstring for why (gmail.readonly is the OAuth scope Jarvis
requests; a reply/delete action here would fail at the API regardless of
what this parser produced).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with modules/gmail/dispatcher.py's handling of these action
# names (there's no separate process boundary here, unlike the office
# modules' pyuno bridge — this frozenset just scopes the AI-structuring
# fallback and validates its response, same role as those modules').
KNOWN_ACTIONS: frozenset[str] = frozenset({"list_recent_emails", "search_emails", "read_email"})

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

DEFAULT_COUNT = 5


@dataclass(frozen=True)
class ParsedGmailCommand:
    action: str
    params: dict[str, object]


def _parse_with_patterns(text: str) -> ParsedGmailCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(r"^(?:покажи|какие)\s+непрочитанные\s+письма$", normalized)
    if match:
        return ParsedGmailCommand(action="list_recent_emails", params={"unread_only": True})

    match = re.match(r"^(?:покажи|какие)\s+последние(?:\s+(\d+))?\s+письма$", normalized)
    if match:
        params: dict[str, object] = {}
        if match.group(1):
            params["count"] = int(match.group(1))
        return ParsedGmailCommand(action="list_recent_emails", params=params)

    if normalized in ("новые письма", "есть новые письма", "что нового в почте"):
        return ParsedGmailCommand(action="list_recent_emails", params={})

    match = re.match(r"^найди\s+письма?\s+от\s+(.+)$", normalized)
    if match:
        return ParsedGmailCommand(action="search_emails", params={"query": f"from:{match.group(1).strip()}"})

    match = re.match(r"^найди\s+письма?\s+(?:с\s+темой|про|о)\s+(.+)$", normalized)
    if match:
        return ParsedGmailCommand(action="search_emails", params={"query": match.group(1).strip()})

    match = re.match(r"^найди\s+письма?\s+(.+)$", normalized)
    if match:
        return ParsedGmailCommand(action="search_emails", params={"query": match.group(1).strip()})

    match = re.match(r"^прочитай\s+(?:последнее\s+)?письмо\s+от\s+(.+)$", normalized)
    if match:
        return ParsedGmailCommand(action="read_email", params={"sender": match.group(1).strip()})

    match = re.match(r"^прочитай\s+письмо\s+(?:с\s+темой|про|о)\s+(.+)$", normalized)
    if match:
        return ParsedGmailCommand(action="read_email", params={"subject_contains": match.group(1).strip()})

    if normalized in ("прочитай последнее письмо", "прочитай письмо", "прочитай почту"):
        return ParsedGmailCommand(action="read_email", params={})

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для чтения почты Gmail (только чтение — отправка и удаление "
        f"недоступны): '{text}'. Вот список доступных действий: {actions}. Определи, какое действие имел "
        "в виду пользователь, и извлеки его параметры (count — сколько писем показать, unread_only "
        "[true|false], query — поисковый запрос в синтаксисе Gmail, sender — отправитель для read_email, "
        "subject_contains — часть темы письма для read_email — только те, что применимы к выбранному "
        "действию и упомянуты в фразе). Если команда не про чтение почты вообще или не подходит ни одно "
        'действие — верни null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате '
        '{"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedGmailCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Gmail AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Gmail AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedGmailCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedGmailCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Gmail AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedGmailCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as this app's other command parsers.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
