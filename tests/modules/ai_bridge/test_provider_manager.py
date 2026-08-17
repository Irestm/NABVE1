from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import modules.ai_bridge.provider_manager as provider_manager_module
from modules.ai_bridge.provider_manager import AllProvidersExhaustedError, ProviderManager
from modules.ai_bridge.providers import PROVIDER_ORDER
from modules.ai_bridge.state_store import StateStore


@pytest.fixture(autouse=True)
def _no_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_manager_module, "apply_system_prompt", lambda text: text)


def _manager(tmp_path: Path) -> ProviderManager:
    manager = ProviderManager(StateStore(tmp_path / "state.db"))
    manager._adapters = {
        name: MagicMock(
            open=AsyncMock(),
            is_limit_reached=AsyncMock(return_value=False),
            send_prompt=AsyncMock(return_value=f"reply from {name}"),
        )
        for name in PROVIDER_ORDER
    }
    return manager


@pytest.mark.asyncio
async def test_send_prompt_returns_reply_from_active_provider(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    reply = await manager.send_prompt("hello")

    assert reply == f"reply from {manager.active_name}"


@pytest.mark.asyncio
async def test_send_prompt_switches_to_next_provider_when_limit_reached(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.active_name
    manager._adapters[first].is_limit_reached = AsyncMock(return_value=True)

    reply = await manager.send_prompt("hello")

    assert manager.active_name != first
    assert "Переключаюсь" in reply
    assert manager.status()["limit_reached"][first] is True


@pytest.mark.asyncio
async def test_send_prompt_raises_all_providers_exhausted_when_every_provider_is_limited(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    for adapter in manager._adapters.values():
        adapter.is_limit_reached = AsyncMock(return_value=True)

    with pytest.raises(AllProvidersExhaustedError):
        await manager.send_prompt("hello")


@pytest.mark.asyncio
async def test_send_prompt_fails_fast_on_non_limit_exception(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.active_name
    manager._adapters[first].send_prompt = AsyncMock(side_effect=RuntimeError("layout changed"))

    with pytest.raises(RuntimeError):
        await manager.send_prompt("hello")

    assert manager.active_name == first


def test_status_reports_active_provider_order_and_limits(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    status = manager.status()

    assert status["active_provider"] == PROVIDER_ORDER[0]
    assert status["order"] == list(PROVIDER_ORDER)
    assert status["limit_reached"] == {name: False for name in PROVIDER_ORDER}


def test_active_provider_persists_across_manager_instances(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    manager = ProviderManager(StateStore(store_path))
    manager._advance_to_next_provider()
    second_provider = manager.active_name

    reloaded = ProviderManager(StateStore(store_path))

    assert reloaded.active_name == second_provider


def test_daily_reset_resets_active_provider_and_limit_flags(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._advance_to_next_provider()
    manager._limit_hit[manager.active_name] = True
    manager._last_reset = (date.today() - timedelta(days=1)).isoformat()

    manager._maybe_daily_reset()

    assert manager.active_name == PROVIDER_ORDER[0]
    assert all(value is False for value in manager._limit_hit.values())


def test_daily_reset_is_a_noop_when_already_reset_today(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._advance_to_next_provider()
    current = manager.active_name

    manager._maybe_daily_reset()

    assert manager.active_name == current
