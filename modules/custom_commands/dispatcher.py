from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.os_adapter import get_os_adapter
from modules.custom_commands.domain import ActionType, CustomCommand
from modules.custom_commands.service_layer import get_all_commands
from modules.custom_commands.uow import CustomCommandsUnitOfWork
from modules.user_profile.domain import CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY
from modules.user_profile.service_layer import get_fact
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_COMMAND_NAME_PREFIX = "custom_"


def _dispatcher_name(command_id: str) -> str:
    return f"{_COMMAND_NAME_PREFIX}{command_id}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def requires_confirmation() -> bool:
    return get_fact(ProfileUnitOfWork(), CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY) == "1"


async def execute_custom_command(command: CustomCommand) -> dict[str, Any]:
    """Runs the four self-contained action types (everything except
    TEXT_INSTRUCTION, which core/voice/pipeline.py handles separately by
    substituting the stored instruction back into the normal
    interpret()/plugin/system-command/ai_bridge chain — see that module's
    custom-command handling). All four reduce to the same
    open-with-OS-default-handler mechanism already used for the built-in
    "open_app" command (core/dispatcher.py::_handle_open_app ->
    core/os_adapter's open_application: xdg-open on Linux, `cmd /c start`
    on Windows — both already open a URL, a media file, or an arbitrary
    executable path exactly as their OS-registered default handler would),
    so no dedicated audio-player/media-viewer code is needed here."""
    payload = command.action_payload
    if command.action_type is ActionType.OPEN_LINK:
        target = payload["url"]
    elif command.action_type in (ActionType.PLAY_AUDIO, ActionType.OPEN_MEDIA):
        target = payload["file_path"]
    elif command.action_type is ActionType.LAUNCH_APP:
        target = payload["executable_path"]
    else:
        raise ValueError(f"execute_custom_command cannot run action_type={command.action_type.value!r}")

    adapter = get_os_adapter()
    success = await asyncio.to_thread(adapter.open_application, target)
    if not success:
        raise RuntimeError(f"Не удалось выполнить свою команду «{command.trigger_phrase}» (цель: {target!r}).")
    return {"message": f"Выполняю: {command.trigger_phrase}."}


class CustomCommandRegistry:
    """Mirrors modules/plugin_agent/plugin_loader.py's PluginRegistry shape
    (dispatcher.register per loaded item + a normalized trigger-phrase
    index, so N user-defined commands become dispatcher commands at
    runtime instead of at import time), but loads structured CustomCommand
    rows from SQLite instead of parsing/importing Python files, and runs a
    fixed action handler instead of sandboxed user code — arbitrary code
    execution was never the goal here, only a handful of canned action
    types."""

    def __init__(self, dispatcher: CommandDispatcher) -> None:
        self._dispatcher = dispatcher
        self._commands: dict[str, CustomCommand] = {}
        self._trigger_index: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _make_handler(command: CustomCommand):
        async def _handler(_params: dict[str, Any]) -> dict[str, Any]:
            return await execute_custom_command(command)

        return _handler

    def _unlocked_unregister(self, command_id: str) -> None:
        # Caller already holds self._lock.
        existing = self._commands.pop(command_id, None)
        self._dispatcher.unregister(_dispatcher_name(command_id))
        if existing is not None:
            normalized = _normalize(existing.trigger_phrase)
            if self._trigger_index.get(normalized) == command_id:
                del self._trigger_index[normalized]

    def register_one(self, command: CustomCommand) -> None:
        with self._lock:
            self._unlocked_unregister(command.id)
            # TEXT_INSTRUCTION is never registered into CommandDispatcher —
            # it needs the full voice pipeline (STT-recognized substitute
            # text re-entering interpret()/plugin/system/ai_bridge), which a
            # synchronous dispatcher handler can't do. Only tracked here for
            # match()/trigger-index purposes; core/voice/pipeline.py checks
            # the action_type itself before deciding to dispatch() vs.
            # substitute-and-continue.
            if command.action_type is not ActionType.TEXT_INSTRUCTION:
                self._dispatcher.register(
                    _dispatcher_name(command.id),
                    self._make_handler(command),
                    # Not registered dangerous=True even for launch_app: the
                    # dispatcher's dangerous flag is frozen at registration
                    # time, but CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY (see
                    # modules/user_profile/domain.py) can be toggled at any
                    # time without necessarily touching a custom command
                    # (which is what triggers a re-register via refresh()) —
                    # that would leave the confirmation gate stale until the
                    # next unrelated CRUD action. core/voice/pipeline.py
                    # checks requires_confirmation() itself, fresh, right
                    # before dispatching a matched launch_app/text_instruction
                    # command instead, the same "re-read every time, don't
                    # cache" approach already used for the stop word/wake
                    # phrase.
                    dangerous=False,
                    description=f"Своя команда: {command.trigger_phrase}",
                )
            self._commands[command.id] = command
            self._trigger_index[_normalize(command.trigger_phrase)] = command.id

    def unregister(self, command_id: str) -> None:
        with self._lock:
            self._unlocked_unregister(command_id)

    def load_all(self) -> None:
        """Full re-sync from SQLite: unregisters everything currently
        tracked first (so a command deleted from the DB since the last
        load actually disappears from the dispatcher too — register_one
        alone only ever adds/replaces by id, it never notices an id that's
        gone missing), then reloads and re-registers every row. Cheap
        enough to call on every CRUD mutation (see module-level refresh())
        rather than trying to diff."""
        with self._lock:
            stale_ids = list(self._commands.keys())
        for command_id in stale_ids:
            self.unregister(command_id)
        for command in get_all_commands(CustomCommandsUnitOfWork()):
            self.register_one(command)

    def match(self, text: str) -> CustomCommand | None:
        normalized = _normalize(text)
        if not normalized:
            return None
        with self._lock:
            command_id = self._trigger_index.get(normalized)
            if command_id is None:
                for pattern, candidate_id in self._trigger_index.items():
                    if pattern and pattern in normalized:
                        command_id = candidate_id
                        break
            return self._commands.get(command_id) if command_id else None


_registry: CustomCommandRegistry | None = None


def get_registry() -> CustomCommandRegistry:
    if _registry is None:
        raise RuntimeError(
            "Реестр своих команд ещё не инициализирован — сначала вызовите register_all_custom_commands()."
        )
    return _registry


def register_all_custom_commands(dispatcher: CommandDispatcher) -> CustomCommandRegistry:
    global _registry
    _registry = CustomCommandRegistry(dispatcher)
    _registry.load_all()
    return _registry


def refresh() -> None:
    """Re-syncs the in-memory registry (and every command's dispatcher
    registration/dangerous-flag) with SQLite — called after any CRUD
    mutation (core/main.py's REST routes) and whenever the "require
    confirmation" profile setting is toggled, so a change takes effect on
    the very next matched utterance without a restart (same reasoning as
    core/voice/pipeline.py re-reading STOP_WORD_KEY/WAKE_PHRASE_KEY on
    every pass instead of once at thread start)."""
    get_registry().load_all()


def match(text: str) -> CustomCommand | None:
    if _registry is None:
        return None
    return _registry.match(text)


def dispatcher_command_name(command_id: str) -> str:
    return _dispatcher_name(command_id)
