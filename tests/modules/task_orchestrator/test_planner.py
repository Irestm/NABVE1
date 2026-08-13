from __future__ import annotations

import asyncio

import modules.task_orchestrator.planner as planner
from core.models import CommandDescriptor
from modules.task_orchestrator.domain import PlanStep

_COMMANDS = [
    CommandDescriptor(name="open_app", dangerous=False, description="Open an app (target)."),
    CommandDescriptor(name="open_media", dangerous=False, description="Play media (kind, query)."),
]


class _FakeAdapter:
    def __init__(self, reply: str, name: str = "fake") -> None:
        self.name = name
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        return self._reply


def test_parses_valid_plan(monkeypatch) -> None:
    reply = '{"steps": [{"command": "open_app", "params": {"target": "calculator"}}]}'
    monkeypatch.setattr(planner, "local_first_chain", lambda: [_FakeAdapter(reply)])

    result = asyncio.run(planner.plan("открой калькулятор", _COMMANDS))

    assert result is not None
    assert result.goal_text == "открой калькулятор"
    assert result.steps == (PlanStep(command="open_app", params={"target": "calculator"}),)


def test_rejects_hallucinated_command(monkeypatch) -> None:
    reply = '{"steps": [{"command": "delete_everything", "params": {}}]}'
    monkeypatch.setattr(planner, "local_first_chain", lambda: [_FakeAdapter(reply)])

    assert asyncio.run(planner.plan("сделай что-нибудь", _COMMANDS)) is None


def test_rejects_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(planner, "local_first_chain", lambda: [_FakeAdapter("это не json")])

    assert asyncio.run(planner.plan("что-то", _COMMANDS)) is None


def test_rejects_empty_steps(monkeypatch) -> None:
    monkeypatch.setattr(planner, "local_first_chain", lambda: [_FakeAdapter('{"steps": []}')])

    assert asyncio.run(planner.plan("невыполнимая задача", _COMMANDS)) is None


def test_rejects_too_many_steps(monkeypatch) -> None:
    one_step = '{"command": "open_app", "params": {}}'
    steps_json = ", ".join(one_step for _ in range(planner.MAX_STEPS + 1))
    reply = f'{{"steps": [{steps_json}]}}'
    monkeypatch.setattr(planner, "local_first_chain", lambda: [_FakeAdapter(reply)])

    assert asyncio.run(planner.plan("много шагов подряд", _COMMANDS)) is None


def test_falls_back_to_next_adapter_on_failure(monkeypatch) -> None:
    class _RaisingAdapter:
        name = "broken"

        async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
            raise RuntimeError("down")

    good_reply = '{"steps": [{"command": "open_app", "params": {}}]}'
    monkeypatch.setattr(
        planner, "local_first_chain", lambda: [_RaisingAdapter(), _FakeAdapter(good_reply)]
    )

    result = asyncio.run(planner.plan("открой что-то", _COMMANDS))

    assert result is not None
    assert result.steps == (PlanStep(command="open_app", params={}),)


def test_returns_none_when_no_commands_available() -> None:
    assert asyncio.run(planner.plan("что угодно", [])) is None
