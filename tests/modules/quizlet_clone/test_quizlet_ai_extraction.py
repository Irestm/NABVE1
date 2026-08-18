from __future__ import annotations

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.quizlet_clone.quizlet_ai_extraction import _parse_pairs, extract_terms_via_ai


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


# --- _parse_pairs ------------------------------------------------------------


def test_parse_pairs_extracts_a_valid_json_array() -> None:
    raw = '[{"term": "hola", "definition": "привет"}, {"term": "gato", "definition": "кот"}]'
    assert _parse_pairs(raw) == [("hola", "привет"), ("gato", "кот")]


def test_parse_pairs_ignores_surrounding_prose() -> None:
    raw = 'Вот пары:\n[{"term": "hola", "definition": "привет"}]\nНадеюсь, помогло!'
    assert _parse_pairs(raw) == [("hola", "привет")]


def test_parse_pairs_skips_malformed_entries() -> None:
    raw = '[{"term": "hola", "definition": "привет"}, {"term": "", "definition": "кот"}, {"term": "gato"}]'
    assert _parse_pairs(raw) == [("hola", "привет")]


def test_parse_pairs_returns_empty_for_no_json_array() -> None:
    assert _parse_pairs("не могу найти пар") == []


def test_parse_pairs_returns_empty_for_invalid_json() -> None:
    assert _parse_pairs("[{not valid json}]") == []


def test_parse_pairs_returns_empty_when_top_level_is_not_a_list() -> None:
    assert _parse_pairs('{"term": "hola", "definition": "привет"}') == []


# --- extract_terms_via_ai -----------------------------------------------------


@pytest.mark.asyncio
async def test_extract_terms_via_ai_uses_local_adapter_first(monkeypatch: pytest.MonkeyPatch) -> None:
    local = _FakeAdapter("local", '[{"term": "hola", "definition": "привет"}]')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = await extract_terms_via_ai("hola — привет")

    assert result == [("hola", "привет")]


@pytest.mark.asyncio
async def test_extract_terms_via_ai_falls_through_to_the_next_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    cloud = _FakeAdapter("cloud", '[{"term": "gato", "definition": "кот"}]')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    result = await extract_terms_via_ai("gato — кот")

    assert result == [("gato", "кот")]


@pytest.mark.asyncio
async def test_extract_terms_via_ai_returns_empty_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = await extract_terms_via_ai("some page text")

    assert result == []


@pytest.mark.asyncio
async def test_extract_terms_via_ai_returns_empty_when_the_model_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = _FakeAdapter("empty", "[]")
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: empty)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = await extract_terms_via_ai("just some navigation chrome, no cards here")

    assert result == []
