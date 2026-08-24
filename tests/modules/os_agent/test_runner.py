from __future__ import annotations

import asyncio

import pytest

from modules.os_agent import runner
from modules.os_agent.domain import MAX_STEPS, AgentDecision
from modules.ui_automation.domain import UIElement, UIStep


class _ActiveWindow:
    def __init__(self, title: str = "Some Window") -> None:
        self.title = title


class _FakeOsAdapter:
    def __init__(self, active: _ActiveWindow | None) -> None:
        self._active = active
        self.clicks: list[tuple[int, int, str]] = []
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def get_active_window(self) -> _ActiveWindow | None:
        return self._active

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press_key(self, key: str) -> None:
        self.pressed.append(key)


def _elements() -> list[UIElement]:
    return [UIElement(index=0, role="page tab", name="Настройки", bbox=(0, 0, 10, 10))]


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, adapter: _FakeOsAdapter) -> None:
    monkeypatch.setattr(runner, "get_os_adapter", lambda: adapter)


def _patch_elements(monkeypatch: pytest.MonkeyPatch, elements=None) -> None:
    async def _fake(active):
        return elements if elements is not None else _elements()

    monkeypatch.setattr(runner.ui_service_layer, "list_active_elements", _fake)


def _patch_decisions(monkeypatch: pytest.MonkeyPatch, decisions: list[AgentDecision]) -> None:
    calls = {"n": 0}

    async def _fake(task, window_title, elements, journal):
        i = min(calls["n"], len(decisions) - 1)
        calls["n"] += 1
        return decisions[i]

    monkeypatch.setattr(runner.planner, "decide_next", _fake)


def test_done_with_no_steps_leaves_queue_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(_ActiveWindow()))
    _patch_elements(monkeypatch)
    _patch_decisions(monkeypatch, [AgentDecision(kind="done", reason="Готово.")])

    session = asyncio.run(runner.run_task("сделай что-нибудь"))

    assert session.outcome == "done"
    assert session.summary == "Готово."
    assert session.pending == []


def test_stuck_leaves_queue_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(_ActiveWindow()))
    _patch_elements(monkeypatch)
    _patch_decisions(monkeypatch, [AgentDecision(kind="stuck", reason="не вижу поле")])

    session = asyncio.run(runner.run_task("сделай что-нибудь"))

    assert session.outcome == "stuck"
    assert session.summary == "не вижу поле"
    assert session.pending == []


def test_free_click_executes_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeOsAdapter(_ActiveWindow())
    _patch_adapter(monkeypatch, adapter)
    _patch_elements(monkeypatch)
    nav_element = UIElement(index=0, role="page tab", name="Настройки", bbox=(10, 20, 30, 40))
    step = UIStep(action="click", element=nav_element)
    _patch_decisions(
        monkeypatch,
        [AgentDecision(kind="step", step=step, reason="open tab"), AgentDecision(kind="done", reason="Готово.")],
    )

    session = asyncio.run(runner.run_task("открой настройки"))

    assert adapter.clicks == [(25, 40, "left")]
    assert session.pending == []
    assert any("Выполнено" in entry for entry in session.journal)


def test_write_step_is_queued_not_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeOsAdapter(_ActiveWindow())
    _patch_adapter(monkeypatch, adapter)
    _patch_elements(monkeypatch)
    step = UIStep(action="type_text", text="привет")
    _patch_decisions(
        monkeypatch,
        [AgentDecision(kind="step", step=step, reason="type"), AgentDecision(kind="done", reason="Готово.")],
    )

    session = asyncio.run(runner.run_task("напиши привет"))

    assert adapter.typed == []
    assert session.pending == [step]
    assert any("Запланировано" in entry for entry in session.journal)


def test_after_first_queued_write_further_free_looking_steps_also_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeOsAdapter(_ActiveWindow())
    _patch_adapter(monkeypatch, adapter)
    _patch_elements(monkeypatch)
    write_step = UIStep(action="type_text", text="привет")
    nav_element = UIElement(index=0, role="page tab", name="Настройки", bbox=(0, 0, 10, 10))
    free_looking_step = UIStep(action="click", element=nav_element)
    _patch_decisions(
        monkeypatch,
        [
            AgentDecision(kind="step", step=write_step),
            AgentDecision(kind="step", step=free_looking_step),
            AgentDecision(kind="done", reason="Готово."),
        ],
    )

    session = asyncio.run(runner.run_task("сделай несколько вещей"))

    assert adapter.clicks == []
    assert session.pending == [write_step, free_looking_step]


def test_step_limit_reached_marks_outcome_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeOsAdapter(_ActiveWindow())
    _patch_adapter(monkeypatch, adapter)
    _patch_elements(monkeypatch)
    nav_element = UIElement(index=0, role="page tab", name="Настройки", bbox=(0, 0, 10, 10))
    step = UIStep(action="click", element=nav_element)

    async def _always_step(task, window_title, elements, journal):
        return AgentDecision(kind="step", step=step)

    monkeypatch.setattr(runner.planner, "decide_next", _always_step)

    session = asyncio.run(runner.run_task("бесконечная задача"))

    assert session.outcome == "limit"
    assert len(adapter.clicks) == MAX_STEPS


def test_decide_next_none_and_no_adapter_available_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(_ActiveWindow()))
    _patch_elements(monkeypatch)

    async def _none(task, window_title, elements, journal):
        return None

    monkeypatch.setattr(runner.planner, "decide_next", _none)
    monkeypatch.setattr(runner.planner, "has_available_adapter", lambda: False)

    session = asyncio.run(runner.run_task("задача"))

    assert session.outcome == "throttled"


def test_decide_next_none_but_adapter_available_is_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(_ActiveWindow()))
    _patch_elements(monkeypatch)

    async def _none(task, window_title, elements, journal):
        return None

    monkeypatch.setattr(runner.planner, "decide_next", _none)
    monkeypatch.setattr(runner.planner, "has_available_adapter", lambda: True)

    session = asyncio.run(runner.run_task("задача"))

    assert session.outcome == "stuck"


def test_no_active_window_is_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(None))
    _patch_elements(monkeypatch)

    session = asyncio.run(runner.run_task("задача"))

    assert session.outcome == "stuck"


def test_no_elements_is_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_adapter(monkeypatch, _FakeOsAdapter(_ActiveWindow()))
    _patch_elements(monkeypatch, elements=[])

    session = asyncio.run(runner.run_task("задача"))

    assert session.outcome == "stuck"
