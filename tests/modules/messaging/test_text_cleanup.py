from __future__ import annotations

import asyncio

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from tests.ai_chain_fakes import use_ai_chain
from modules.messaging.text_cleanup import clean_dictated_text


class _FakeAdapter:
    def __init__(self, name: str, reply: str) -> None:
        self.name = name
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        return self._reply


class _FailingAdapter:
    name = "failing"

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        raise RuntimeError("boom")


def test_clean_dictated_text_returns_ai_cleaned_text(monkeypatch: pytest.MonkeyPatch) -> None:
    use_ai_chain(monkeypatch, _FakeAdapter("local", "Привет! Как дела?"), _FailingAdapter())

    result = asyncio.run(clean_dictated_text("привет как дела"))

    assert result == "Привет! Как дела?"


def test_clean_dictated_text_strips_surrounding_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    use_ai_chain(monkeypatch, _FakeAdapter("local", '"Хорошо."'), _FailingAdapter())

    result = asyncio.run(clean_dictated_text("хорошо"))

    assert result == "Хорошо."


def test_clean_dictated_text_falls_through_to_cloud_when_local_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    use_ai_chain(monkeypatch, _FailingAdapter(), _FakeAdapter("ai_bridge", "Уже еду."))

    result = asyncio.run(clean_dictated_text("уже еду"))

    assert result == "Уже еду."


def test_clean_dictated_text_falls_back_to_raw_text_when_every_adapter_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unedited dictation is still a perfectly sendable message — failing
    # to clean it up must never block the reply from going out at all.
    use_ai_chain(monkeypatch, _FailingAdapter())

    result = asyncio.run(clean_dictated_text("привет как дела"))

    assert result == "привет как дела"


def test_clean_dictated_text_falls_back_to_raw_text_on_empty_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    use_ai_chain(monkeypatch, _FakeAdapter("local", "   "), _FailingAdapter())

    result = asyncio.run(clean_dictated_text("привет как дела"))

    assert result == "привет как дела"


def test_clean_dictated_text_returns_empty_string_unchanged_without_calling_any_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = use_ai_chain(monkeypatch, _FailingAdapter())

    result = asyncio.run(clean_dictated_text("   "))

    assert result == ""
    assert fake.requests == 0
