from __future__ import annotations

import asyncio

from modules.discussion_mode import opinion


class _Adapter:
    name = "fake"

    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def test_build_opinion_returns_first_adapter_reply(monkeypatch) -> None:
    monkeypatch.setattr(opinion, "candidate_chain", lambda text: [_Adapter("Я за ипотеку: аренда — деньги в никуда.")])

    result = asyncio.run(opinion.build_opinion("спикер 1: ипотека\nспикер 2: аренда", "джарвис", "ru"))

    assert "ипотек" in result.lower()


def test_build_opinion_skips_failing_adapters(monkeypatch) -> None:
    monkeypatch.setattr(
        opinion,
        "candidate_chain",
        lambda text: [_Adapter(RuntimeError("down")), _Adapter("Второй ответил.")],
    )

    result = asyncio.run(opinion.build_opinion("спикер 1: что-то", "джарвис", "ru"))

    assert result == "Второй ответил."


def test_build_opinion_without_transcript_returns_fallback() -> None:
    result = asyncio.run(opinion.build_opinion("   ", "джарвис", "ru"))
    assert result == opinion._FALLBACK


def test_build_opinion_all_adapters_fail(monkeypatch) -> None:
    monkeypatch.setattr(opinion, "candidate_chain", lambda text: [_Adapter(RuntimeError("x"))])
    result = asyncio.run(opinion.build_opinion("спикер 1: тема", "джарвис", "ru"))
    assert "не получилось" in result.lower()
