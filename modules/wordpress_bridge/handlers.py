from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.wordpress_bridge import service_layer


async def _handle_generate_fix(params: dict[str, Any]) -> dict[str, Any]:
    description = params.get("problem_description")
    if not description:
        raise ValueError("Не указано описание проблемы.")
    context_snippet = params.get("context_snippet")
    return await asyncio.to_thread(service_layer.generate_php_fix, str(description), context_snippet)


async def _handle_list_fixes(_params: dict[str, Any]) -> dict[str, Any]:
    return {"fixes": await asyncio.to_thread(service_layer.list_php_fixes)}


async def _handle_get_fix_code(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Не указано имя файла.")
    code = await asyncio.to_thread(service_layer.get_php_fix_code, str(filename))
    return {"filename": filename, "code": code}


async def _handle_review_fix(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Не указано имя файла.")
    await asyncio.to_thread(service_layer.mark_php_fix_reviewed, str(filename))
    return {"filename": filename}


async def _handle_discard_fix(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Не указано имя файла.")
    await asyncio.to_thread(service_layer.discard_php_fix, str(filename))
    return {"filename": filename}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "wordpress_generate_fix",
        _handle_generate_fix,
        dangerous=False,
        description=(
            "Сгенерировать PHP-исправление через Claude Code CLI для проблемы темы/плагина WordPress "
            "(problem_description, опционально context_snippet). Никогда не применяется на живой сайт "
            "— сохраняется только локально в modules/wordpress_bridge/_generated_fixes/ для ручной проверки."
        ),
    )
    dispatcher.register(
        "wordpress_list_fixes",
        _handle_list_fixes,
        dangerous=False,
        description="Показать список ранее сгенерированных PHP-исправлений, ожидающих проверки.",
    )
    dispatcher.register(
        "wordpress_get_fix_code",
        _handle_get_fix_code,
        dangerous=False,
        description="Показать код сгенерированного PHP-исправления (filename).",
    )
    dispatcher.register(
        "wordpress_review_fix",
        _handle_review_fix,
        dangerous=False,
        description="Отметить сгенерированное PHP-исправление как проверенное (filename).",
    )
    dispatcher.register(
        "wordpress_discard_fix",
        _handle_discard_fix,
        dangerous=False,
        description="Удалить сгенерированное PHP-исправление (filename).",
    )
