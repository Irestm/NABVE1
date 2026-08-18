from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.timer import service_layer


def _format_duration(duration: timedelta) -> str:
    total_seconds = max(0, int(duration.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if seconds or not parts:
        parts.append(f"{seconds} сек")
    return " ".join(parts)


async def _handle_toggle_timer(params: dict[str, Any]) -> dict[str, Any]:
    # One command for both directions, like _handle_toggle_stopwatch below
    # — but a timer (unlike the single stopwatch) isn't binary, so the
    # branch is on the params given, not on "is anything currently
    # running": minutes given starts a new one; no minutes cancels
    # (a specific timer_id if given, else every active timer). Voice/AI
    # calls can still target one timer by id; the UI button (see
    # core/command_ui_metadata.py's toggle_timer entry) only ever omits
    # minutes to mean "cancel all", since it has no per-timer picker.
    minutes = params.get("minutes")
    if minutes is not None:
        minutes = float(minutes)
        if minutes <= 0:
            raise ValueError("Продолжительность таймера должна быть больше нуля.")
        label = (params.get("label") or "").strip() or "Таймер"
        timer_id = service_layer.start_timer(minutes * 60, label)
        return {
            "timer_id": timer_id,
            "running": True,
            "message": (
                f"«{label}» поставлен на {_format_duration(timedelta(minutes=minutes))} — "
                "сообщу, когда время выйдет."
            ),
        }

    timer_id_raw = params.get("timer_id")
    if timer_id_raw is not None:
        cancelled = service_layer.cancel_timer(int(timer_id_raw))
        message = "Таймер отменён." if cancelled else "Таймер с таким номером не найден."
        return {"cancelled_count": int(cancelled), "running": False, "message": message}

    active = service_layer.list_active_timers()
    for timer in active:
        service_layer.cancel_timer(int(timer["id"]))
    message = f"Отменено таймеров: {len(active)}." if active else "Активных таймеров нет."
    return {"cancelled_count": len(active), "running": False, "message": message}


async def _handle_list_active_timers(_params: dict[str, Any]) -> dict[str, Any]:
    active = service_layer.list_active_timers()
    if not active:
        message = "Активных таймеров нет."
    else:
        listed = "; ".join(
            f"{timer['label']} — осталось {_format_duration(timedelta(seconds=timer['remaining_seconds']))}"
            for timer in active
        )
        message = f"Активные таймеры: {listed}."
    return {"timers": active, "message": message}


async def _handle_toggle_stopwatch(_params: dict[str, Any]) -> dict[str, Any]:
    # One button/command for both directions — the caller (voice or the
    # single CommandPanel button) doesn't need to track "is it running" to
    # know which one to say/press; the current state decides.
    if service_layer.stopwatch_elapsed() is None:
        service_layer.start_stopwatch()
        return {"running": True, "message": "Секундомер запущен."}

    elapsed = service_layer.stop_stopwatch()
    return {
        "running": False,
        "elapsed_seconds": elapsed.total_seconds(),
        "message": f"Секундомер: {_format_duration(elapsed)}.",
    }


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "toggle_timer",
        _handle_toggle_timer,
        dangerous=False,
        description=(
            "Если указаны minutes — поставить таймер на это число минут (опционально label), сообщит, когда "
            "время выйдет. Если minutes не указаны — отменить таймер по timer_id, или все активные таймеры, "
            "если timer_id тоже не указан."
        ),
    )
    dispatcher.register(
        "list_active_timers",
        _handle_list_active_timers,
        dangerous=False,
        description="Показать все активные таймеры и сколько времени у каждого осталось.",
    )
    dispatcher.register(
        "toggle_stopwatch",
        _handle_toggle_stopwatch,
        dangerous=False,
        description="Запустить секундомер, если он выключен, или остановить и показать прошедшее время, если включён.",
    )
