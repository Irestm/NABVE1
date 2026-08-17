from __future__ import annotations

import time
from datetime import datetime, timedelta

from core.message_bus import MessageBus
from modules.messaging import service_layer
from modules.messaging.domain import PendingMessage, PendingMessageStatus
from modules.messaging.events import MessageReceived
from modules.messaging.snooze_checker import SnoozeChecker
from modules.messaging.uow import MessagingUnitOfWork


def _uow(tmp_path) -> MessagingUnitOfWork:
    return MessagingUnitOfWork(tmp_path / "assistant.db")


def test_check_once_republishes_elapsed_snoozes_and_flips_status(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        message_id = uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="123",
                sender_label="Ира",
                text="Привет",
                status=PendingMessageStatus.SNOOZED,
                snooze_until=datetime.now() - timedelta(minutes=1),
            )
        )
        uow.commit()

    bus = MessageBus()
    received: list[MessageReceived] = []

    async def _record(event: MessageReceived) -> None:
        received.append(event)

    bus.subscribe(MessageReceived, _record)
    checker = SnoozeChecker(uow_factory=lambda: uow, bus=bus)

    checker._check_once()

    assert [e.message_id for e in received] == [message_id]
    with uow:
        stored = uow.messages.get(message_id)
    assert stored is not None
    assert stored.status is PendingMessageStatus.PENDING
    assert stored.snooze_until is None


def test_check_once_ignores_snoozes_not_yet_elapsed(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.messages.add(
            PendingMessage(
                source="telegram",
                sender_identifier="123",
                sender_label="Ира",
                text="Привет",
                status=PendingMessageStatus.SNOOZED,
                snooze_until=datetime.now() + timedelta(hours=1),
            )
        )
        uow.commit()

    bus = MessageBus()
    received: list[MessageReceived] = []
    bus.subscribe(MessageReceived, lambda event: received.append(event))
    checker = SnoozeChecker(uow_factory=lambda: uow, bus=bus)

    checker._check_once()

    assert received == []


def test_check_once_swallows_service_layer_exceptions(tmp_path, monkeypatch) -> None:
    checker = SnoozeChecker(uow_factory=lambda: _uow(tmp_path))

    async def _boom(_uow, _bus, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_layer, "check_due_snoozes", _boom)

    checker._check_once()  # must not raise


def test_start_and_stop_lifecycle(tmp_path) -> None:
    checker = SnoozeChecker(interval_seconds=60, uow_factory=lambda: _uow(tmp_path))
    assert checker.is_running is False

    checker.start()
    try:
        assert checker.is_running is True
    finally:
        checker.stop()

    assert checker.is_running is False


def test_run_loop_ticks_until_stopped(tmp_path) -> None:
    ticks: list[int] = []
    checker = SnoozeChecker(interval_seconds=0, uow_factory=lambda: _uow(tmp_path))
    checker._check_once = lambda: ticks.append(1)  # type: ignore[method-assign]

    checker.start()
    time.sleep(0.05)
    checker.stop()

    assert len(ticks) >= 1
