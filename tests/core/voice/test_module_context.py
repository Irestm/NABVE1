from __future__ import annotations

import pytest

from core.voice import module_context


@pytest.fixture(autouse=True)
def _reset_module_context() -> None:
    module_context.deactivate()
    yield
    module_context.deactivate()


def test_current_is_none_when_never_activated() -> None:
    assert module_context.current() is None


def test_activate_then_current_returns_the_name() -> None:
    module_context.activate("fitness")
    assert module_context.current() == "fitness"


def test_current_expires_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(module_context.time, "monotonic", lambda: clock["t"])

    module_context.activate("fitness")
    clock["t"] += 10.0
    assert module_context.current(timeout_seconds=5) is None


def test_touch_resets_the_inactivity_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(module_context.time, "monotonic", lambda: clock["t"])

    module_context.activate("fitness")
    clock["t"] += 3.0
    module_context.touch()
    clock["t"] += 3.0

    assert module_context.current(timeout_seconds=5) == "fitness"


def test_deactivate_with_matching_name_clears_it() -> None:
    module_context.activate("fitness")
    assert module_context.deactivate("fitness") is True
    assert module_context.current() is None


def test_deactivate_with_mismatched_name_is_a_no_op() -> None:
    module_context.activate("fitness")
    assert module_context.deactivate("some_other_module") is False
    assert module_context.current() == "fitness"


def test_deactivate_without_name_clears_whatever_is_active() -> None:
    module_context.activate("fitness")
    assert module_context.deactivate() is True
    assert module_context.current() is None


def test_deactivate_when_nothing_active_returns_false() -> None:
    assert module_context.deactivate() is False
