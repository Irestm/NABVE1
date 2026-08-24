from __future__ import annotations

import asyncio

import pytest

from modules.os_agent import planner
from modules.os_agent.domain import AgentSession
from modules.ui_automation.domain import UIElement, UIStep


def _elements() -> list[UIElement]:
    return [
        UIElement(index=0, role="push button", name="Сохранить", bbox=(10, 10, 50, 20)),
        UIElement(index=1, role="page tab", name="Настройки", bbox=(100, 100, 60, 20)),
    ]


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


# --- _parse_decision -----------------------------------------------------


def test_parse_decision_click_step() -> None:
    elements = _elements()
    decision = planner._parse_decision(
        '{"kind": "step", "action": "click", "target_index": 1, "reason": "open settings"}', elements
    )
    assert decision is not None
    assert decision.kind == "step"
    assert decision.step == UIStep(action="click", element=elements[1])
    assert decision.reason == "open settings"


def test_parse_decision_type_text_step() -> None:
    decision = planner._parse_decision('{"kind": "step", "action": "type_text", "text": "hi"}', _elements())
    assert decision is not None
    assert decision.step == UIStep(action="type_text", text="hi")


def test_parse_decision_done() -> None:
    decision = planner._parse_decision('{"kind": "done", "reason": "Готово."}', _elements())
    assert decision is not None
    assert decision.kind == "done"
    assert decision.reason == "Готово."


def test_parse_decision_stuck() -> None:
    decision = planner._parse_decision('{"kind": "stuck", "reason": "не вижу поле"}', _elements())
    assert decision is not None
    assert decision.kind == "stuck"


def test_parse_decision_unknown_kind_is_none() -> None:
    assert planner._parse_decision('{"kind": "wander"}', _elements()) is None


def test_parse_decision_invalid_json_is_none() -> None:
    assert planner._parse_decision("not json", _elements()) is None


def test_parse_decision_step_with_out_of_range_index_is_none() -> None:
    assert planner._parse_decision('{"kind": "step", "action": "click", "target_index": 9}', _elements()) is None


def test_parse_decision_extracts_json_from_surrounding_text() -> None:
    raw = 'Хорошо! {"kind": "done", "reason": "готово"} вот так'
    decision = planner._parse_decision(raw, _elements())
    assert decision is not None
    assert decision.kind == "done"


# --- decide_next / has_configured_key / has_available_adapter ------------


def test_has_configured_key_false_without_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: None)
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)
    assert planner.has_configured_key() is False


def test_has_configured_key_true_with_gemini_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: _FakeAdapter("gemini", "{}"))
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)
    assert planner.has_configured_key() is True


def test_decide_next_returns_none_without_any_configured_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: None)
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)

    decision = asyncio.run(planner.decide_next("open settings", "Window", _elements(), []))

    assert decision is None
    assert planner.has_available_adapter() is False


def test_decide_next_returns_none_when_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: _FakeAdapter("gemini", "{}"))
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)
    monkeypatch.setattr(planner.quota_tracker, "is_near_limit", lambda *a, **k: True)

    decision = asyncio.run(planner.decide_next("open settings", "Window", _elements(), []))

    assert decision is None
    assert planner.has_available_adapter() is False


def test_decide_next_uses_first_successful_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    gemini = _FakeAdapter("gemini", '{"kind": "done", "reason": "готово"}')
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: gemini)
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)
    monkeypatch.setattr(planner.quota_tracker, "is_near_limit", lambda *a, **k: False)

    decision = asyncio.run(planner.decide_next("task", "Window", _elements(), []))

    assert decision is not None
    assert decision.kind == "done"


def test_decide_next_falls_through_a_failing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(
        planner.api_providers, "get_claude_adapter", lambda: _FakeAdapter("claude", '{"kind": "stuck", "reason": "x"}')
    )
    monkeypatch.setattr(planner.quota_tracker, "is_near_limit", lambda *a, **k: False)

    decision = asyncio.run(planner.decide_next("task", "Window", _elements(), []))

    assert decision is not None
    assert decision.kind == "stuck"


# --- explain ---------------------------------------------------------------


def test_explain_returns_none_without_any_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: None)
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)

    result = asyncio.run(planner.explain(AgentSession(task="open settings")))

    assert result is None


def test_explain_returns_stripped_adapter_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner.api_providers, "get_gemini_adapter", lambda: _FakeAdapter("gemini", "  потому что так проще  "))
    monkeypatch.setattr(planner.api_providers, "get_claude_adapter", lambda: None)
    monkeypatch.setattr(planner.quota_tracker, "is_near_limit", lambda *a, **k: False)

    result = asyncio.run(planner.explain(AgentSession(task="open settings", journal=["Выполнено: X"])))

    assert result == "потому что так проще"
