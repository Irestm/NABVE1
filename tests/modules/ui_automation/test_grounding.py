from __future__ import annotations

import asyncio

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.ui_automation.domain import UIElement, UIStep
from modules.ui_automation.grounding import _parse_grounding, ground


def _elements() -> list[UIElement]:
    return [
        UIElement(index=0, role="push button", name="Сохранить", bbox=(10, 10, 50, 20)),
        UIElement(index=1, role="link", name="Тренды", bbox=(100, 100, 60, 20)),
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


# --- _parse_grounding --------------------------------------------------


def test_parse_grounding_single_click_step() -> None:
    elements = _elements()
    steps = _parse_grounding('{"steps": [{"action": "click", "target_index": 1}]}', elements)
    assert steps == [UIStep(action="click", element=elements[1])]


def test_parse_grounding_extracts_json_from_surrounding_text() -> None:
    elements = _elements()
    raw = 'Конечно! Вот действие: {"steps": [{"action": "click", "target_index": 0}]} спасибо'
    steps = _parse_grounding(raw, elements)
    assert steps == [UIStep(action="click", element=elements[0])]


def test_parse_grounding_click_then_type_sequence() -> None:
    elements = _elements()
    raw = (
        '{"steps": [{"action": "click", "target_index": 0}, '
        '{"action": "type_text", "text": "привет"}]}'
    )
    steps = _parse_grounding(raw, elements)
    assert steps == [
        UIStep(action="click", element=elements[0]),
        UIStep(action="type_text", text="привет"),
    ]


def test_parse_grounding_press_key_step() -> None:
    steps = _parse_grounding('{"steps": [{"action": "press_key", "key": "Enter"}]}', _elements())
    assert steps == [UIStep(action="press_key", key="Enter")]


def test_parse_grounding_empty_steps_is_none() -> None:
    assert _parse_grounding('{"steps": []}', _elements()) is None


def test_parse_grounding_invalid_json_is_none() -> None:
    assert _parse_grounding("not json at all", _elements()) is None


def test_parse_grounding_unknown_action_is_none() -> None:
    assert _parse_grounding('{"steps": [{"action": "scroll"}]}', _elements()) is None


def test_parse_grounding_out_of_range_target_index_is_none() -> None:
    assert _parse_grounding('{"steps": [{"action": "click", "target_index": 99}]}', _elements()) is None


def test_parse_grounding_missing_target_index_is_none() -> None:
    assert _parse_grounding('{"steps": [{"action": "click"}]}', _elements()) is None


def test_parse_grounding_empty_type_text_is_none() -> None:
    assert _parse_grounding('{"steps": [{"action": "type_text", "text": ""}]}', _elements()) is None


def test_parse_grounding_empty_press_key_is_none() -> None:
    assert _parse_grounding('{"steps": [{"action": "press_key", "key": ""}]}', _elements()) is None


def test_parse_grounding_too_many_steps_is_none() -> None:
    raw_steps = ", ".join('{"action": "press_key", "key": "Tab"}' for _ in range(6))
    assert _parse_grounding(f'{{"steps": [{raw_steps}]}}', _elements()) is None


def test_parse_grounding_one_invalid_step_rejects_whole_response() -> None:
    # A structurally invalid step anywhere in the list rejects the entire
    # response rather than silently running a partial/different sequence.
    raw = (
        '{"steps": [{"action": "click", "target_index": 0}, '
        '{"action": "click", "target_index": 99}]}'
    )
    assert _parse_grounding(raw, _elements()) is None


# --- ground() ------------------------------------------------------------


def test_ground_returns_none_when_no_elements() -> None:
    assert asyncio.run(ground("Some Window", [], "нажми на тренды")) is None


def test_ground_uses_first_successful_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    elements = _elements()
    local = _FakeAdapter("local", '{"steps": [{"action": "click", "target_index": 1}]}')
    cloud = _FakeAdapter("ai_bridge", '{"steps": [{"action": "click", "target_index": 0}]}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    steps = asyncio.run(ground("Some Window", elements, "нажми на тренды"))

    assert steps == [UIStep(action="click", element=elements[1])]


def test_ground_falls_through_a_failing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    elements = _elements()
    cloud = _FakeAdapter("ai_bridge", '{"steps": [{"action": "click", "target_index": 0}]}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    steps = asyncio.run(ground("Some Window", elements, "нажми сохранить"))

    assert steps == [UIStep(action="click", element=elements[0])]


def test_ground_falls_through_an_unparseable_response(monkeypatch: pytest.MonkeyPatch) -> None:
    elements = _elements()
    local = _FakeAdapter("local", "не могу понять")
    cloud = _FakeAdapter("ai_bridge", '{"steps": [{"action": "click", "target_index": 0}]}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    steps = asyncio.run(ground("Some Window", elements, "нажми сохранить"))

    assert steps == [UIStep(action="click", element=elements[0])]


def test_ground_returns_none_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    elements = _elements()
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    assert asyncio.run(ground("Some Window", elements, "нажми сохранить")) is None
