from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.capabilities import CAPABILITIES_MESSAGES
from core.logger import get_logger
from core.models import CommandDescriptor, CommandResponse, CommandStatus
from core.os_adapter import get_os_adapter

logger = get_logger(__name__)

CommandHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class PendingConfirmation:
    command: str
    params: dict[str, Any]
    created_at: float


class UnknownCommandError(Exception):
    pass


class CommandDispatcher:
    def __init__(self, confirmation_ttl_seconds: int = 60) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._dangerous: set[str] = set()
        self._descriptions: dict[str, str] = {}
        self._pending: dict[str, PendingConfirmation] = {}
        self._confirmation_ttl = confirmation_ttl_seconds

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        dangerous: bool = False,
        description: str = "",
    ) -> None:
        if name in self._handlers:
            raise ValueError(f"Command '{name}' is already registered")
        self._handlers[name] = handler
        self._descriptions[name] = description
        if dangerous:
            self._dangerous.add(name)

    def unregister(self, name: str) -> None:
        self._handlers.pop(name, None)
        self._descriptions.pop(name, None)
        self._dangerous.discard(name)

    def list_commands(self) -> list[CommandDescriptor]:
        return [
            CommandDescriptor(
                name=name,
                dangerous=name in self._dangerous,
                description=self._descriptions.get(name, ""),
            )
            for name in sorted(self._handlers)
        ]

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, pending in self._pending.items()
            if now - pending.created_at > self._confirmation_ttl
        ]
        for token in expired:
            del self._pending[token]

    async def dispatch(self, command: str, params: dict[str, Any]) -> CommandResponse:
        if command not in self._handlers:
            raise UnknownCommandError(command)

        if command in self._dangerous:
            self._purge_expired()
            token = uuid.uuid4().hex
            self._pending[token] = PendingConfirmation(
                command=command, params=params, created_at=time.monotonic()
            )
            logger.info("Command '%s' requires confirmation (token=%s)", command, token)
            return CommandResponse(
                status=CommandStatus.CONFIRMATION_REQUIRED,
                command=command,
                message="This action requires explicit confirmation.",
                token=token,
            )

        return await self._execute(command, params)

    async def confirm(self, token: str, approved: bool) -> CommandResponse:
        self._purge_expired()
        pending = self._pending.pop(token, None)
        if pending is None:
            return CommandResponse(
                status=CommandStatus.FAILED,
                command="",
                message="Unknown or expired confirmation token.",
            )

        if not approved:
            logger.info("Command '%s' cancelled by user (token=%s)", pending.command, token)
            return CommandResponse(
                status=CommandStatus.CANCELLED,
                command=pending.command,
                message="Command cancelled.",
            )

        return await self._execute(pending.command, pending.params)

    async def _execute(self, command: str, params: dict[str, Any]) -> CommandResponse:
        handler = self._handlers[command]
        try:
            result = await handler(params)
            logger.info("Command '%s' executed with params=%s", command, params)
            # Handlers that actually have something to say (a search summary,
            # "event created for <date>", the current time, ...) put it in
            # result["message"]; core.voice.responses.localize_response speaks
            # it verbatim instead of the generic "Done" when present. Handlers
            # with nothing more to say than "it happened" (open_app, hide_window,
            # ...) just omit it, same as before.
            message = result.get("message") if isinstance(result, dict) else None
            return CommandResponse(
                status=CommandStatus.EXECUTED,
                command=command,
                message=message or "Command executed.",
                result=result,
            )
        except Exception as exc:
            logger.exception("Command '%s' failed", command)
            return CommandResponse(
                status=CommandStatus.FAILED,
                command=command,
                message=str(exc),
            )


async def _handle_open_app(params: dict[str, Any]) -> dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter 'target'")
    adapter = get_os_adapter()
    success = await asyncio.to_thread(adapter.open_application, target)
    if not success:
        raise RuntimeError(f"Could not open application '{target}'")
    return {"target": target}


async def _handle_close_app(params: dict[str, Any]) -> dict[str, Any]:
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter 'target'")
    adapter = get_os_adapter()
    success = await asyncio.to_thread(adapter.close_application, target)
    if not success:
        raise RuntimeError(f"Could not find an open application matching '{target}' to close")
    return {"target": target}


async def _handle_shutdown(_params: dict[str, Any]) -> dict[str, Any]:
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.shutdown)
    return {}


async def _handle_restart(_params: dict[str, Any]) -> dict[str, Any]:
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.restart)
    return {}


async def _handle_click(params: dict[str, Any]) -> dict[str, Any]:
    x, y = params.get("x"), params.get("y")
    if x is None or y is None:
        raise ValueError("Missing required parameters 'x' and 'y'")
    button = params.get("button", "left")
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.click, int(x), int(y), button)
    return {"x": x, "y": y, "button": button}


async def _handle_move_mouse(params: dict[str, Any]) -> dict[str, Any]:
    x, y = params.get("x"), params.get("y")
    if x is None or y is None:
        raise ValueError("Missing required parameters 'x' and 'y'")
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.move_mouse, int(x), int(y))
    return {"x": x, "y": y}


async def _handle_type_text(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.type_text, text)
    return {"text": text}


async def _handle_press_key(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Missing required parameter 'key'")
    adapter = get_os_adapter()
    await asyncio.to_thread(adapter.press_key, key)
    return {"key": key}


async def _handle_list_windows(_params: dict[str, Any]) -> dict[str, Any]:
    adapter = get_os_adapter()
    titles = await asyncio.to_thread(adapter.list_windows)
    return {"windows": titles}


async def _handle_list_capabilities(params: dict[str, Any]) -> dict[str, Any]:
    language = params.get("language", "ru")
    message = CAPABILITIES_MESSAGES.get(language, CAPABILITIES_MESSAGES["ru"])
    return {"message": message}


async def _handle_focus_window(params: dict[str, Any]) -> dict[str, Any]:
    title = params.get("title")
    if not title:
        raise ValueError("Missing required parameter 'title'")
    adapter = get_os_adapter()
    focused = await asyncio.to_thread(adapter.focus_window, title)
    if not focused:
        raise RuntimeError(f"Could not find window matching '{title}'")
    return {"title": title}


def build_dispatcher(confirmation_ttl_seconds: int = 60) -> CommandDispatcher:
    dispatcher = CommandDispatcher(confirmation_ttl_seconds=confirmation_ttl_seconds)
    dispatcher.register(
        "open_app",
        _handle_open_app,
        dangerous=False,
        description="Open an application or file by name/path (target).",
    )
    dispatcher.register(
        "close_app",
        _handle_close_app,
        dangerous=False,
        description="Close a running application by (partial) window title match (target).",
    )
    dispatcher.register(
        "shutdown",
        _handle_shutdown,
        dangerous=True,
        description="Shut down the computer.",
    )
    dispatcher.register(
        "restart",
        _handle_restart,
        dangerous=True,
        description="Restart the computer.",
    )
    dispatcher.register(
        "click",
        _handle_click,
        dangerous=False,
        description="Click at screen coordinates (x, y, button).",
    )
    dispatcher.register(
        "move_mouse",
        _handle_move_mouse,
        dangerous=False,
        description="Move the mouse cursor to screen coordinates (x, y).",
    )
    dispatcher.register(
        "type_text",
        _handle_type_text,
        dangerous=False,
        description="Type text at the current cursor focus (text).",
    )
    dispatcher.register(
        "press_key",
        _handle_press_key,
        dangerous=False,
        description="Press a single keyboard key (key).",
    )
    dispatcher.register(
        "list_windows",
        _handle_list_windows,
        dangerous=False,
        description="List titles of open windows.",
    )
    dispatcher.register(
        "focus_window",
        _handle_focus_window,
        dangerous=False,
        description="Focus a window by (partial) title match (title).",
    )
    dispatcher.register(
        "list_capabilities",
        _handle_list_capabilities,
        dangerous=False,
        description="Describe what this assistant can do, as a human-readable summary (optional language).",
    )
    return dispatcher
