from __future__ import annotations

import pytest

from modules.timer import handlers, service_layer


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    service_layer._active_timers.clear()
    service_layer._stopwatch_started_at = None
    yield
    for active in list(service_layer._active_timers.values()):
        active.task.cancel()
    service_layer._active_timers.clear()
    service_layer._stopwatch_started_at = None


async def test_toggle_timer_rejects_non_positive_minutes() -> None:
    with pytest.raises(ValueError, match="больше нуля"):
        await handlers._handle_toggle_timer({"minutes": 0})


async def test_toggle_timer_with_minutes_starts_a_timer() -> None:
    result = await handlers._handle_toggle_timer({"minutes": 5, "label": "Пицца"})

    assert result["running"] is True
    assert "«Пицца»" in result["message"]
    assert "5 мин" in result["message"]

    service_layer.cancel_timer(result["timer_id"])


async def test_toggle_timer_with_no_minutes_and_no_id_cancels_all_active_timers() -> None:
    await handlers._handle_toggle_timer({"minutes": 5})
    await handlers._handle_toggle_timer({"minutes": 10})

    result = await handlers._handle_toggle_timer({})

    assert result["running"] is False
    assert result["cancelled_count"] == 2
    assert service_layer.list_active_timers() == []


async def test_toggle_timer_with_an_unknown_id_reports_not_found() -> None:
    result = await handlers._handle_toggle_timer({"timer_id": 999})

    assert result["running"] is False
    assert result["cancelled_count"] == 0
    assert "не найден" in result["message"]


async def test_list_active_timers_when_empty() -> None:
    result = await handlers._handle_list_active_timers({})

    assert result["timers"] == []
    assert "нет" in result["message"]


async def test_toggle_stopwatch_start_then_stop_reports_elapsed_time() -> None:
    started = await handlers._handle_toggle_stopwatch({})
    assert started["running"] is True

    stopped = await handlers._handle_toggle_stopwatch({})

    assert stopped["running"] is False
    assert "Секундомер:" in stopped["message"]
    assert stopped["elapsed_seconds"] >= 0


def test_register_commands_registers_all_three() -> None:
    from core.dispatcher import CommandDispatcher

    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)

    names = {d.name for d in dispatcher.list_commands()}
    assert {"toggle_timer", "list_active_timers", "toggle_stopwatch"} <= names
