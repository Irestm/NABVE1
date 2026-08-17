from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from core.config import DATA_DIR
from core.logger import get_logger
from modules.custom_commands.domain import ActionType, CustomCommand, LOGGED_ACTION_TYPES
from modules.custom_commands.uow import CustomCommandsUnitOfWork

logger = get_logger(__name__)

# Kept under DATA_DIR (gitignored, per-machine runtime data — same as
# core/voice/config.py's VOICES_DIR, modules/plugin_agent's PLUGINS_DIR,
# core/config.py's MEETING_RECORDINGS_DIR), not inside this module's own
# source-tree directory: a user's attached mp3/photos/videos have no
# business ending up inside a version-controlled folder.
ATTACHMENTS_DIR: Path = DATA_DIR / "custom_commands" / "attachments"


def save_attachment(command_id: str, filename: str, data: bytes) -> Path:
    dest_dir = ATTACHMENTS_DIR / command_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / (filename or "attachment")
    destination.write_bytes(data)
    return destination


def _delete_attachments(command_id: str) -> None:
    shutil.rmtree(ATTACHMENTS_DIR / command_id, ignore_errors=True)


def _maybe_log_risky(action: str, command: CustomCommand) -> None:
    # ТЗ п.4: create/edit of launch_app and text_instruction commands must
    # be logged in full — these are the two action types that either run an
    # arbitrary executable or feed arbitrary text back into the AI/command
    # pipeline as if the user had said it themselves.
    if command.action_type in LOGGED_ACTION_TYPES:
        logger.info(
            "Custom command %s: id=%s trigger=%r action_type=%s payload=%s",
            action,
            command.id,
            command.trigger_phrase,
            command.action_type.value,
            command.action_payload,
        )


def create_command(
    uow: CustomCommandsUnitOfWork,
    trigger_phrase: str,
    action_type: ActionType,
    action_payload: dict,
    attachment: tuple[str, bytes] | None = None,
) -> CustomCommand:
    command_id = uuid.uuid4().hex
    payload = dict(action_payload)
    if attachment is not None:
        filename, data = attachment
        payload["file_path"] = str(save_attachment(command_id, filename, data))

    command = CustomCommand(id=command_id, trigger_phrase=trigger_phrase, action_type=action_type, action_payload=payload)
    with uow:
        uow.commands.add(command)
        uow.commit()
    _maybe_log_risky("created", command)
    return command


def get_all_commands(uow: CustomCommandsUnitOfWork) -> list[CustomCommand]:
    with uow:
        return uow.commands.list_all()


def get_command(uow: CustomCommandsUnitOfWork, command_id: str) -> CustomCommand | None:
    with uow:
        return uow.commands.get(command_id)


def update_command(
    uow: CustomCommandsUnitOfWork,
    command_id: str,
    trigger_phrase: str,
    action_type: ActionType,
    action_payload: dict,
    attachment: tuple[str, bytes] | None = None,
) -> CustomCommand | None:
    payload = dict(action_payload)
    if attachment is not None:
        filename, data = attachment
        payload["file_path"] = str(save_attachment(command_id, filename, data))

    with uow:
        existing = uow.commands.get(command_id)
        if existing is None:
            return None
        existing.trigger_phrase = trigger_phrase
        existing.action_type = action_type
        existing.action_payload = payload
        uow.commands.update(existing)
        uow.commit()
        updated = existing
    _maybe_log_risky("updated", updated)
    return updated


def delete_command(uow: CustomCommandsUnitOfWork, command_id: str) -> bool:
    with uow:
        removed = uow.commands.delete(command_id)
        uow.commit()
    if removed:
        _delete_attachments(command_id)
    return removed
