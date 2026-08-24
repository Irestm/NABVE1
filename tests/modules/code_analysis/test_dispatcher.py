from __future__ import annotations

import pytest

from core.dispatcher import CommandDispatcher
from modules.code_analysis import dispatcher as code_dispatcher
from modules.code_analysis import service_layer


def test_register_commands_registers_all_three() -> None:
    dispatcher = CommandDispatcher()

    code_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {
        code_dispatcher.COMMAND_ANALYZE_CODE,
        code_dispatcher.COMMAND_ANALYZE_GITHUB_FILE,
        code_dispatcher.COMMAND_ANALYZE_ACTIVE_EDITOR,
    }


async def test_analyze_code_handler_delegates(monkeypatch) -> None:
    async def fake_analyze_code(code: str, instruction: str) -> str:
        assert code == "print(1)"
        assert instruction == "объясни"
        return "Печатает единицу."

    monkeypatch.setattr(service_layer, "analyze_code", fake_analyze_code)

    result = await code_dispatcher._analyze_code({"code": "print(1)", "instruction": "объясни"})

    assert result == {"message": "Печатает единицу.", "analysis": "Печатает единицу."}


async def test_analyze_code_handler_rejects_missing_code() -> None:
    with pytest.raises(ValueError):
        await code_dispatcher._analyze_code({"instruction": "объясни"})


async def test_analyze_github_file_handler_fetches_then_analyzes(monkeypatch) -> None:
    async def fake_fetch(url: str) -> str:
        assert url == "https://github.com/o/r/blob/main/a.py"
        return "print(1)"

    async def fake_analyze_code(code: str, instruction: str) -> str:
        assert code == "print(1)"
        return "Печатает единицу."

    monkeypatch.setattr(service_layer, "fetch_github_file", fake_fetch)
    monkeypatch.setattr(service_layer, "analyze_code", fake_analyze_code)

    result = await code_dispatcher._analyze_github_file(
        {"url": "https://github.com/o/r/blob/main/a.py", "instruction": "объясни"}
    )

    assert result["analysis"] == "Печатает единицу."


async def test_analyze_github_file_handler_rejects_missing_url() -> None:
    with pytest.raises(ValueError):
        await code_dispatcher._analyze_github_file({"instruction": "объясни"})


async def test_analyze_active_editor_handler_delegates(monkeypatch) -> None:
    async def fake_analyze_active_editor(instruction: str) -> str:
        assert instruction == "найди баг"
        return "Баг на строке 10."

    monkeypatch.setattr(service_layer, "analyze_active_editor", fake_analyze_active_editor)

    result = await code_dispatcher._analyze_active_editor({"instruction": "найди баг"})

    assert result == {"message": "Баг на строке 10.", "analysis": "Баг на строке 10."}


async def test_analyze_active_editor_handler_rejects_missing_instruction() -> None:
    with pytest.raises(ValueError):
        await code_dispatcher._analyze_active_editor({})
