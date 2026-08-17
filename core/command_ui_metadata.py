from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamField:
    name: str
    type: str  # "number" | "text" | "select"
    label: str
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] | None = None


@dataclass(frozen=True)
class CommandUIMeta:
    label: str
    icon: str  # lucide-react component name, e.g. "Power"
    params_schema: tuple[ParamField, ...] | None


# UI-facing subset of core/dispatcher.py's registered commands — the ones
# that make sense as a standalone button (as opposed to open_app, click,
# type_text, ... which need free-text targets the voice/AI path resolves).
# Keyed by the exact dispatcher command name so GET /api/commands/ui can
# merge this with the live CommandDescriptor list (name/dangerous/description)
# instead of duplicating that bookkeeping here.
COMMAND_UI_METADATA: dict[str, CommandUIMeta] = {
    "shutdown": CommandUIMeta("Выключить ПК", "Power", None),
    "restart": CommandUIMeta("Перезагрузить ПК", "RefreshCw", None),
    "set_volume": CommandUIMeta(
        "Громкость",
        "Volume2",
        (ParamField("percent", "number", "Громкость, %", min=0, max=100),),
    ),
    "toggle_mute": CommandUIMeta("Заглушить/включить звук", "VolumeX", None),
    "minimize_window": CommandUIMeta("Скрыть окно", "Minimize2", None),
    "close_os_window": CommandUIMeta("Закрыть окно", "X", None),
    "close_browser_tab": CommandUIMeta("Закрыть вкладку", "X", None),
    "create_folder": CommandUIMeta(
        "Создать папку",
        "FolderPlus",
        (ParamField("path", "text", "Путь к папке"),),
    ),
    "move_folder": CommandUIMeta(
        "Переместить папку",
        "FolderInput",
        (
            ParamField("source", "text", "Откуда"),
            ParamField("destination", "text", "Куда"),
        ),
    ),
    "delete_folder": CommandUIMeta(
        "Удалить папку",
        "Trash2",
        (ParamField("path", "text", "Путь к папке"),),
    ),
    "switch_keyboard_layout": CommandUIMeta(
        "Сменить раскладку",
        "Languages",
        (ParamField("language_code", "select", "Язык", options=("ru", "uk", "en")),),
    ),
    "get_battery_status": CommandUIMeta("Проверить заряд батареи", "Battery", None),
    "check_system_updates": CommandUIMeta("Проверить обновления", "DownloadCloud", None),
}
