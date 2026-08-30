from __future__ import annotations

from datetime import datetime, timedelta

from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from modules.delayed_execution import service_layer
from modules.delayed_execution.scheduler import DelayedCommandRunner
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork


def test_tick_fires_a_due_command(tmp_db_path) -> None:
    fired: list[str] = []

    async def noop(_params):
        fired.append("noop")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("noop", noop, dangerous=False, description="")

    factory = lambda: DelayedExecutionUnitOfWork(db_path=tmp_db_path)
    service_layer.schedule(
        factory(), Command(name="noop", params={}), datetime.now() - timedelta(seconds=1), "x"
    )

    runner = DelayedCommandRunner(dispatcher, interval_seconds=999, uow_factory=factory)
    runner._tick()

    assert fired == ["noop"]
    assert service_layer.list_pending(factory()) == []


def test_tick_is_safe_with_nothing_due(tmp_db_path) -> None:
    dispatcher = CommandDispatcher()
    factory = lambda: DelayedExecutionUnitOfWork(db_path=tmp_db_path)
    runner = DelayedCommandRunner(dispatcher, interval_seconds=999, uow_factory=factory)
    runner._tick()  # must not raise
