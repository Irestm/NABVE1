from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.config import DATA_DIR
from core.logger import get_logger
from modules.conversation_log.domain import ConversationTurn, Role, Source

logger = get_logger(__name__)

_LOG_PATH: Path = DATA_DIR / "conversation_log.jsonl"

# Rolling cap so an always-on assistant can't grow this file without
# bound. This is a convenience transcript for the user to read back, not
# an audit trail - on crossing the cap the oldest turns are dropped.
_MAX_TURNS: int = 5000


class ConversationLog:
    """Append-only newline-delimited JSON transcript of user/assistant
    turns. One instance is shared by the voice loop (its own background
    thread) and the FastAPI handlers (the asyncio loop), so every file
    touch is guarded by a lock - the writes are tiny and infrequent
    (a handful of turns per minute at most), so a plain threading.Lock is
    more than enough and keeps the store dependency-free."""

    def __init__(self, path: Path = _LOG_PATH, max_turns: int = _MAX_TURNS) -> None:
        self._path = path
        self._max_turns = max_turns
        self._lock = threading.Lock()

    def append(self, role: Role, text: str, source: Source) -> ConversationTurn:
        turn = ConversationTurn(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            role=role,
            text=text.strip(),
            source=source,
        )
        line = json.dumps(turn.to_dict(), ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._trim_locked()
        return turn

    def clear(self) -> None:
        """Drops the whole transcript. Called on backend startup (the
        transcript is session-scoped — see core/main.py's lifespan) and by
        the "Контекст" button in the text-chat panel."""
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass

    def recent(self, limit: int = 200) -> list[ConversationTurn]:
        if limit <= 0:
            return []
        with self._lock:
            lines = self._read_lines_locked()
        turns: list[ConversationTurn] = []
        for line in lines[-limit:]:
            parsed = _parse_line(line)
            if parsed is not None:
                turns.append(parsed)
        return turns

    def _read_lines_locked(self) -> list[str]:
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                return [line for line in handle.read().splitlines() if line.strip()]
        except FileNotFoundError:
            return []

    def _trim_locked(self) -> None:
        lines = self._read_lines_locked()
        if len(lines) <= self._max_turns:
            return
        kept = lines[-self._max_turns :]
        with self._path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(kept) + "\n")


def _parse_line(line: str) -> ConversationTurn | None:
    try:
        return ConversationTurn.from_dict(json.loads(line))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Skipping a malformed conversation_log line: %s", exc)
        return None
