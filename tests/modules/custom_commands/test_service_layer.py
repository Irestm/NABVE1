from __future__ import annotations

from modules.custom_commands import service_layer
from modules.custom_commands.domain import ActionType
from modules.custom_commands.uow import CustomCommandsUnitOfWork


def _uow(tmp_path) -> CustomCommandsUnitOfWork:
    return CustomCommandsUnitOfWork(tmp_path / "assistant.db")


def test_create_command_persists_and_returns_a_generated_id(tmp_path) -> None:
    uow = _uow(tmp_path)

    command = service_layer.create_command(uow, "открой почту", ActionType.OPEN_LINK, {"url": "https://mail.example"})

    assert command.id
    assert command.trigger_phrase == "открой почту"
    assert command.action_type is ActionType.OPEN_LINK
    assert command.action_payload == {"url": "https://mail.example"}
    assert [c.id for c in service_layer.get_all_commands(uow)] == [command.id]


def test_create_command_with_attachment_copies_file_under_data_dir(tmp_path, monkeypatch) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setattr(service_layer, "ATTACHMENTS_DIR", attachments_dir)
    uow = _uow(tmp_path)

    command = service_layer.create_command(
        uow, "сыграй трек", ActionType.PLAY_AUDIO, {}, attachment=("song.mp3", b"fake-mp3-bytes")
    )

    saved_path = attachments_dir / command.id / "song.mp3"
    assert saved_path.is_file()
    assert saved_path.read_bytes() == b"fake-mp3-bytes"
    assert command.action_payload["file_path"] == str(saved_path)


def test_update_command_replaces_fields(tmp_path) -> None:
    uow = _uow(tmp_path)
    command = service_layer.create_command(uow, "открой почту", ActionType.OPEN_LINK, {"url": "https://old.example"})

    updated = service_layer.update_command(
        uow, command.id, "открой ящик", ActionType.OPEN_LINK, {"url": "https://new.example"}
    )

    assert updated is not None
    assert updated.trigger_phrase == "открой ящик"
    assert updated.action_payload == {"url": "https://new.example"}
    stored = service_layer.get_command(uow, command.id)
    assert stored is not None
    assert stored.action_payload == {"url": "https://new.example"}


def test_update_command_returns_none_for_unknown_id(tmp_path) -> None:
    uow = _uow(tmp_path)

    result = service_layer.update_command(uow, "does-not-exist", "x", ActionType.OPEN_LINK, {"url": "https://x"})

    assert result is None


def test_delete_command_removes_row_and_attachments(tmp_path, monkeypatch) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setattr(service_layer, "ATTACHMENTS_DIR", attachments_dir)
    uow = _uow(tmp_path)
    command = service_layer.create_command(
        uow, "сыграй трек", ActionType.PLAY_AUDIO, {}, attachment=("song.mp3", b"data")
    )
    assert (attachments_dir / command.id).is_dir()

    removed = service_layer.delete_command(uow, command.id)

    assert removed is True
    assert service_layer.get_command(uow, command.id) is None
    assert not (attachments_dir / command.id).exists()


def test_delete_command_returns_false_for_unknown_id(tmp_path) -> None:
    uow = _uow(tmp_path)

    assert service_layer.delete_command(uow, "does-not-exist") is False


def test_create_command_logs_launch_app_in_full(tmp_path, caplog) -> None:
    uow = _uow(tmp_path)
    with caplog.at_level("INFO"):
        service_layer.create_command(
            uow, "запусти игру", ActionType.LAUNCH_APP, {"executable_path": "/opt/game/run.sh"}
        )

    assert any("launch_app" in record.message and "/opt/game/run.sh" in record.message for record in caplog.records)


def test_create_command_does_not_log_open_link_as_risky(tmp_path, caplog) -> None:
    uow = _uow(tmp_path)
    with caplog.at_level("INFO"):
        service_layer.create_command(uow, "открой почту", ActionType.OPEN_LINK, {"url": "https://mail.example"})

    assert not any("Custom command created" in record.message for record in caplog.records)
