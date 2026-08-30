from __future__ import annotations

import threading
from pathlib import Path

from modules.conversation_log.domain import ConversationTurn
from modules.conversation_log.store import ConversationLog


def _make_log(tmp_path: Path, max_turns: int = 5000) -> ConversationLog:
    return ConversationLog(path=tmp_path / "conversation_log.jsonl", max_turns=max_turns)


def test_append_persists_a_turn_and_recent_reads_it_back(tmp_path: Path) -> None:
    log = _make_log(tmp_path)

    turn = log.append("user", "  какая погода в киеве  ", "voice")

    assert turn == ConversationTurn(
        timestamp=turn.timestamp, role="user", text="какая погода в киеве", source="voice"
    )
    assert log.recent() == [turn]


def test_recent_returns_turns_in_append_order(tmp_path: Path) -> None:
    log = _make_log(tmp_path)

    first = log.append("user", "привет", "text")
    second = log.append("assistant", "здравствуйте", "text")
    third = log.append("user", "спасибо", "voice")

    assert log.recent() == [first, second, third]


def test_recent_honours_the_limit_and_keeps_the_newest(tmp_path: Path) -> None:
    log = _make_log(tmp_path)
    for index in range(10):
        log.append("user", f"сообщение {index}", "text")

    tail = log.recent(limit=3)

    assert [turn.text for turn in tail] == ["сообщение 7", "сообщение 8", "сообщение 9"]


def test_recent_on_a_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _make_log(tmp_path).recent() == []


def test_recent_with_a_non_positive_limit_returns_empty(tmp_path: Path) -> None:
    log = _make_log(tmp_path)
    log.append("user", "что-то", "text")

    assert log.recent(limit=0) == []
    assert log.recent(limit=-5) == []


def test_append_trims_the_file_to_max_turns(tmp_path: Path) -> None:
    log = _make_log(tmp_path, max_turns=5)
    for index in range(12):
        log.append("user", f"строка {index}", "text")

    lines = (tmp_path / "conversation_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert [turn.text for turn in log.recent()] == [f"строка {index}" for index in range(7, 12)]


def test_recent_skips_malformed_lines(tmp_path: Path) -> None:
    log = _make_log(tmp_path)
    good = log.append("user", "нормальная строка", "text")

    with (tmp_path / "conversation_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("не json\n")
        handle.write('{"timestamp": "2026-08-27T00:00:00+00:00"}\n')

    assert log.recent() == [good]


def test_concurrent_appends_do_not_lose_turns(tmp_path: Path) -> None:
    log = _make_log(tmp_path)

    def worker(worker_id: int) -> None:
        for index in range(20):
            log.append("user", f"w{worker_id}-{index}", "voice")

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(log.recent(limit=1000)) == 100
