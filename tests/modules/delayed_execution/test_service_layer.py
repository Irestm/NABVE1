from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from modules.delayed_execution import service_layer
from modules.delayed_execution.domain import DelayedCommandStatus
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork


def _uow(tmp_db_path):
    return DelayedExecutionUnitOfWork(db_path=tmp_db_path)


def _dispatcher() -> tuple[CommandDispatcher, list[str]]:
    fired: list[str] = []

    async def noop(_params):
        fired.append("noop")
        return {}

    async def boom(_params):
        fired.append("boom")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", noop, dangerous=False, description="")
    dispatcher.register("boom", boom, dangerous=True, description="")
    return dispatcher, fired


def test_schedule_then_list_pending(tmp_db_path) -> None:
    run_at = datetime.now() + timedelta(minutes=10)
    task_id = service_layer.schedule(
        _uow(tmp_db_path), Command(name="noop", params={"x": "1"}), run_at, "сделай что-то через 10 минут"
    )
    pending = service_layer.list_pending(_uow(tmp_db_path))
    assert [t.id for t in pending] == [task_id]
    assert pending[0].command_name == "noop"
    assert pending[0].command_params == {"x": "1"}


def test_cancel_marks_cancelled(tmp_db_path) -> None:
    task_id = service_layer.schedule(
        _uow(tmp_db_path), Command(name="noop", params={}), datetime.now() + timedelta(hours=1), "x"
    )
    assert service_layer.cancel(_uow(tmp_db_path), task_id) is True
    assert service_layer.list_pending(_uow(tmp_db_path)) == []
    # second cancel is a no-op, not an error
    assert service_layer.cancel(_uow(tmp_db_path), task_id) is False


def test_run_due_fires_only_past_due_and_marks_done(tmp_db_path) -> None:
    dispatcher, fired = _dispatcher()
    past = service_layer.schedule(
        _uow(tmp_db_path), Command(name="noop", params={}), datetime.now() - timedelta(seconds=1), "past"
    )
    future = service_layer.schedule(
        _uow(tmp_db_path), Command(name="noop", params={}), datetime.now() + timedelta(hours=1), "future"
    )

    handled = asyncio.run(service_layer.run_due(_uow(tmp_db_path), dispatcher))

    assert handled == 1
    assert fired == ["noop"]
    remaining = {t.id for t in service_layer.list_pending(_uow(tmp_db_path))}
    assert remaining == {future}
    with _uow(tmp_db_path) as uow:
        assert uow.commands.get(past).status is DelayedCommandStatus.DONE


def test_run_due_uses_preconfirmed_path_for_dangerous(tmp_db_path) -> None:
    dispatcher, fired = _dispatcher()
    service_layer.schedule(
        _uow(tmp_db_path),
        Command(name="boom", params={}),
        datetime.now() - timedelta(seconds=1),
        "выключи компьютер через час",
        pre_confirmed=True,
    )

    handled = asyncio.run(service_layer.run_due(_uow(tmp_db_path), dispatcher))

    # Dangerous command actually ran (not stuck at confirmation) because it
    # was pre-confirmed at schedule time.
    assert handled == 1
    assert fired == ["boom"]


def test_run_due_marks_failed_when_dispatch_raises(tmp_db_path) -> None:
    async def kaboom(_params):
        raise RuntimeError("nope")

    dispatcher = CommandDispatcher()
    dispatcher.register("kaboom", kaboom, dangerous=False, description="")
    task_id = service_layer.schedule(
        _uow(tmp_db_path), Command(name="kaboom", params={}), datetime.now() - timedelta(seconds=1), "x"
    )

    asyncio.run(service_layer.run_due(_uow(tmp_db_path), dispatcher))

    with _uow(tmp_db_path) as uow:
        assert uow.commands.get(task_id).status is DelayedCommandStatus.FAILED
