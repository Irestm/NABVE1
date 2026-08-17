from __future__ import annotations

import threading
import time

from modules.plugin_agent.promotion_worker import GapPromotionWorker


def test_is_running_reflects_thread_lifecycle() -> None:
    worker = GapPromotionWorker(interval_seconds=60, uow_factory=lambda: object())

    assert worker.is_running is False
    worker.start()
    try:
        assert worker.is_running is True
    finally:
        worker.stop()
    assert worker.is_running is False


def test_start_is_idempotent_when_already_running() -> None:
    worker = GapPromotionWorker(interval_seconds=60, uow_factory=lambda: object())
    worker.start()
    first_thread = worker._thread
    try:
        worker.start()
        assert worker._thread is first_thread
    finally:
        worker.stop()


def test_run_calls_process_next_ready_candidate_with_a_fresh_uow(monkeypatch) -> None:
    made_uows: list[object] = []
    called_with: list[object] = []
    ticked = threading.Event()

    def fake_uow_factory():
        uow = object()
        made_uows.append(uow)
        return uow

    async def fake_process_next_ready_candidate(uow):
        called_with.append(uow)
        ticked.set()

    monkeypatch.setattr(
        "modules.plugin_agent.promotion_worker.service_layer.process_next_ready_candidate",
        fake_process_next_ready_candidate,
    )

    worker = GapPromotionWorker(interval_seconds=60, uow_factory=fake_uow_factory)
    worker.start()
    try:
        assert ticked.wait(timeout=2)
    finally:
        worker.stop()

    assert called_with == made_uows[:1]


def test_a_tick_exception_does_not_kill_the_worker_thread(monkeypatch) -> None:
    call_count = 0
    second_call = threading.Event()

    async def flaky_process_next_ready_candidate(uow):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        second_call.set()

    monkeypatch.setattr(
        "modules.plugin_agent.promotion_worker.service_layer.process_next_ready_candidate",
        flaky_process_next_ready_candidate,
    )

    worker = GapPromotionWorker(interval_seconds=0.01, uow_factory=lambda: object())
    worker.start()
    try:
        assert second_call.wait(timeout=2)
        assert worker.is_running is True
    finally:
        worker.stop()
