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
    # When true, CommandPanel.tsx's isFormComplete lets the field stay
    # empty — used where "nothing entered" is itself a meaningful choice
    # (see toggle_timer: minutes given starts a new timer, left blank
    # cancels every active one), not just an unfinished form.
    optional: bool = False


@dataclass(frozen=True)
class CommandUIMeta:
    label: str
    icon: str  # lucide-react component name, e.g. "Power"
    params_schema: tuple[ParamField, ...] | None
    # Group id — see GROUP_LABELS below. Every command button belongs to
    # exactly one group; CommandPanel.tsx renders one labeled section per
    # group, in GROUP_ORDER, each with its own accent color instead of the
    # old one-color-per-button-by-index scheme.
    group: str = "misc"


# Display label for each group id, in the order CommandPanel.tsx should
# render them — GROUP_ORDER is the single source of truth for both.
GROUP_LABELS: dict[str, str] = {
    "power": "Питание и система",
    "sound": "Звук",
    "windows": "Окна и вкладки",
    "files": "Файлы",
    "time_lang": "Время и язык",
    "games": "Игры",
    "modes": "Режимы",
}
GROUP_ORDER: tuple[str, ...] = ("power", "sound", "windows", "files", "time_lang", "games", "modes")


# UI-facing subset of core/dispatcher.py's registered commands — the ones
# that make sense as a standalone button (as opposed to open_app, click,
# type_text, ... which need free-text targets the voice/AI path resolves).
# Keyed by the exact dispatcher command name so GET /api/commands/ui can
# merge this with the live CommandDescriptor list (name/dangerous/description)
# instead of duplicating that bookkeeping here.
COMMAND_UI_METADATA: dict[str, CommandUIMeta] = {
    "shutdown": CommandUIMeta("Выключить ПК", "Power", None, group="power"),
    "restart": CommandUIMeta("Перезагрузить ПК", "RefreshCw", None, group="power"),
    "lock_screen": CommandUIMeta("Заблокировать экран", "Lock", None, group="power"),
    "get_battery_status": CommandUIMeta("Проверить заряд батареи", "Battery", None, group="power"),
    "check_system_updates": CommandUIMeta("Проверить обновления", "DownloadCloud", None, group="power"),
    "software_install": CommandUIMeta(
        "Установить программу",
        "PackagePlus",
        (ParamField("app", "text", "Название программы"),),
        group="power",
    ),
    "set_volume": CommandUIMeta(
        "Громкость",
        "Volume2",
        (ParamField("percent", "number", "Громкость, %", min=0, max=100),),
        group="sound",
    ),
    "toggle_mute": CommandUIMeta("Заглушить/включить звук", "VolumeX", None, group="sound"),
    "minimize_window": CommandUIMeta("Скрыть окно", "Minimize2", None, group="windows"),
    "close_os_window": CommandUIMeta("Закрыть окно", "X", None, group="windows"),
    "close_browser_tab": CommandUIMeta("Закрыть вкладку", "X", None, group="windows"),
    "create_folder": CommandUIMeta(
        "Создать папку",
        "FolderPlus",
        (ParamField("path", "text", "Путь к папке"),),
        group="files",
    ),
    "move_folder": CommandUIMeta(
        "Переместить папку",
        "FolderInput",
        (
            ParamField("source", "text", "Откуда"),
            ParamField("destination", "text", "Куда"),
        ),
        group="files",
    ),
    "delete_folder": CommandUIMeta(
        "Удалить папку",
        "Trash2",
        (ParamField("path", "text", "Путь к папке"),),
        group="files",
    ),
    "switch_keyboard_layout": CommandUIMeta(
        "Сменить раскладку",
        "Languages",
        (ParamField("language_code", "select", "Язык", options=("ru", "uk", "en")),),
        group="time_lang",
    ),
    # One button for both directions, like toggle_stopwatch — minutes given
    # starts a new timer, left blank cancels every active one (see
    # modules.timer.handlers._handle_toggle_timer). Still no separate
    # "label" field: the handler accepts one from a voice/AI-classified
    # call, but the UI button always uses the default.
    "toggle_timer": CommandUIMeta(
        "Таймер",
        "Timer",
        (ParamField("minutes", "number", "Минут (пусто — отменить все активные)", min=1, max=180, optional=True),),
        group="time_lang",
    ),
    "toggle_stopwatch": CommandUIMeta("Секундомер", "Watch", None, group="time_lang"),
    # One button for both games (was two separate ones) — picking which is
    # now the same params_schema-driven "select" dialog every other
    # multi-choice command already uses (see switch_keyboard_layout above),
    # instead of a dedicated button per game.
    "start_board_game": CommandUIMeta(
        "Игры",
        "Gamepad2",
        (ParamField("game", "select", "Игра", options=("Шахматы", "Шашки")),),
        group="games",
    ),
    # Signals the running mic loop into modules/discussion_mode — no params;
    # exit is by voice ("выйди из режима дискуссии"). See
    # modules/discussion_mode/handlers.py.
    "discussion_start": CommandUIMeta("Режим дискуссии", "MessagesSquare", None, group="modes"),
}
