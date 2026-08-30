from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.calendar.domain import RecurrenceRule
from modules.calendar.extraction import ExtractedEvent, _parse_extraction, extract_event


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


# --- _parse_extraction -----------------------------------------------------


def test_parses_valid_extraction() -> None:
    raw = '{"title": "Купить молока", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 15}'
    result = _parse_extraction(raw)
    assert result == ExtractedEvent(
        title="Купить молока",
        event_time=datetime(2026, 8, 6, 9, 0, 0),
        remind_before_minutes=15,
        recurrence=RecurrenceRule.NONE,
        category=None,
    )


def test_parses_recurrence_and_category_when_present() -> None:
    raw = (
        '{"title": "Пить воду", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 0, '
        '"recurrence": "daily", "category": "Здоровье"}'
    )
    result = _parse_extraction(raw)
    assert result is not None
    assert result.recurrence == RecurrenceRule.DAILY
    assert result.category == "Здоровье"


def test_unknown_recurrence_value_falls_back_to_none() -> None:
    raw = (
        '{"title": "Что-то", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 0, '
        '"recurrence": "biweekly", "category": null}'
    )
    result = _parse_extraction(raw)
    assert result is not None
    assert result.recurrence == RecurrenceRule.NONE


def test_extracts_json_from_surrounding_text() -> None:
    raw = 'Конечно! {"title": "Позвонить маме", "event_time": "2026-08-07T18:00:00", "remind_before_minutes": 10} готово'
    result = _parse_extraction(raw)
    assert result is not None
    assert result.title == "Позвонить маме"


def test_missing_remind_before_minutes_uses_default() -> None:
    raw = '{"title": "Сходить к врачу", "event_time": "2026-08-06T09:00:00"}'
    result = _parse_extraction(raw)
    assert result is not None
    assert result.remind_before_minutes == 30


def test_null_title_returns_none() -> None:
    raw = '{"title": null, "event_time": null, "remind_before_minutes": null}'
    assert _parse_extraction(raw) is None


def test_unparseable_event_time_returns_none() -> None:
    raw = '{"title": "Что-то", "event_time": "не дата", "remind_before_minutes": 10}'
    assert _parse_extraction(raw) is None


def test_invalid_json_returns_none() -> None:
    assert _parse_extraction("это не JSON вообще") is None


def test_negative_remind_before_is_clamped_to_zero() -> None:
    raw = '{"title": "Что-то", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": -5}'
    result = _parse_extraction(raw)
    assert result is not None
    assert result.remind_before_minutes == 0


# --- extract_event -----------------------------------------------------------


def test_extract_event_uses_local_adapter_first(monkeypatch: pytest.MonkeyPatch) -> None:
    local = _FakeAdapter("local", '{"title": "Купить молока", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 15}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(extract_event("купить молока завтра утром", now=datetime(2026, 8, 5, 12, 0, 0)))

    assert result is not None
    assert result.title == "Купить молока"


def test_extract_event_falls_through_to_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    cloud = _FakeAdapter("ai_bridge", '{"title": "Позвонить маме", "event_time": "2026-08-07T18:00:00", "remind_before_minutes": 5}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    result = asyncio.run(extract_event("позвонить маме в пятницу вечером"))

    assert result is not None
    assert result.title == "Позвонить маме"


def test_extract_event_returns_none_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    assert asyncio.run(extract_event("что-нибудь")) is None


def test_extract_event_returns_none_when_model_cannot_parse_request(monkeypatch: pytest.MonkeyPatch) -> None:
    unclear = _FakeAdapter("local", '{"title": null, "event_time": null, "remind_before_minutes": null}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: unclear)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    assert asyncio.run(extract_event("бла бла бла")) is None


def test_critical_keyword_in_source_text_sets_the_flag() -> None:
    raw = '{"title": "Принять лекарство", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 5}'
    assert _parse_extraction(raw, "критически важно принять лекарство в 9").critical is True
    assert _parse_extraction(raw, "принять лекарство в 9").critical is False


def test_critical_defaults_to_false_without_source_text() -> None:
    raw = '{"title": "X", "event_time": "2026-08-06T09:00:00", "remind_before_minutes": 5}'
    assert _parse_extraction(raw).critical is False
