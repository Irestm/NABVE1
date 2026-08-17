from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.wordpress_bridge import service_layer


async def _handle_generate_fix(params: dict[str, Any]) -> dict[str, Any]:
    description = params.get("problem_description")
    if not description:
        raise ValueError("Missing required parameter 'problem_description'")
    context_snippet = params.get("context_snippet")
    return await asyncio.to_thread(service_layer.generate_php_fix, str(description), context_snippet)


async def _handle_list_fixes(_params: dict[str, Any]) -> dict[str, Any]:
    return {"fixes": await asyncio.to_thread(service_layer.list_php_fixes)}


async def _handle_get_fix_code(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Missing required parameter 'filename'")
    code = await asyncio.to_thread(service_layer.get_php_fix_code, str(filename))
    return {"filename": filename, "code": code}


async def _handle_review_fix(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Missing required parameter 'filename'")
    await asyncio.to_thread(service_layer.mark_php_fix_reviewed, str(filename))
    return {"filename": filename}


async def _handle_discard_fix(params: dict[str, Any]) -> dict[str, Any]:
    filename = params.get("filename")
    if not filename:
        raise ValueError("Missing required parameter 'filename'")
    await asyncio.to_thread(service_layer.discard_php_fix, str(filename))
    return {"filename": filename}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "wordpress_generate_fix",
        _handle_generate_fix,
        dangerous=False,
        description=(
            "Generate a PHP fix via the Claude Code CLI for a WordPress theme/plugin problem "
            "(problem_description, optional context_snippet). Never applied to any live site — "
            "only saved locally under modules/wordpress_bridge/_generated_fixes/ for manual review."
        ),
    )
    dispatcher.register(
        "wordpress_list_fixes",
        _handle_list_fixes,
        dangerous=False,
        description="List previously generated PHP fixes awaiting review.",
    )
    dispatcher.register(
        "wordpress_get_fix_code",
        _handle_get_fix_code,
        dangerous=False,
        description="Show the code of a generated PHP fix (filename).",
    )
    dispatcher.register(
        "wordpress_review_fix",
        _handle_review_fix,
        dangerous=False,
        description="Mark a generated PHP fix as reviewed (filename).",
    )
    dispatcher.register(
        "wordpress_discard_fix",
        _handle_discard_fix,
        dangerous=False,
        description="Delete a generated PHP fix (filename).",
    )
