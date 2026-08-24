from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.code_analysis import service_layer

COMMAND_ANALYZE_CODE = "analyze_code"
COMMAND_ANALYZE_GITHUB_FILE = "analyze_github_file"
COMMAND_ANALYZE_ACTIVE_EDITOR = "analyze_active_editor"


async def _analyze_code(params: dict[str, Any]) -> dict[str, Any]:
    code = params.get("code")
    instruction = params.get("instruction")
    if not code:
        raise ValueError("Не указан код для анализа.")
    if not instruction:
        raise ValueError("Не указана задача.")
    result = await service_layer.analyze_code(code, instruction)
    return {"message": result, "analysis": result}


async def _analyze_github_file(params: dict[str, Any]) -> dict[str, Any]:
    url = params.get("url")
    instruction = params.get("instruction")
    if not url:
        raise ValueError("Не указана ссылка на GitHub.")
    if not instruction:
        raise ValueError("Не указана задача.")
    code = await service_layer.fetch_github_file(url)
    result = await service_layer.analyze_code(code, instruction)
    return {"message": result, "analysis": result}


async def _analyze_active_editor(params: dict[str, Any]) -> dict[str, Any]:
    instruction = params.get("instruction")
    if not instruction:
        raise ValueError("Не указана задача.")
    result = await service_layer.analyze_active_editor(instruction)
    return {"message": result, "analysis": result}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(COMMAND_ANALYZE_CODE, _analyze_code, description="Проанализировать вставленный код")
    dispatcher.register(
        COMMAND_ANALYZE_GITHUB_FILE, _analyze_github_file, description="Проанализировать файл кода с GitHub"
    )
    dispatcher.register(
        COMMAND_ANALYZE_ACTIVE_EDITOR,
        _analyze_active_editor,
        description="Проанализировать код в открытом редакторе",
    )
