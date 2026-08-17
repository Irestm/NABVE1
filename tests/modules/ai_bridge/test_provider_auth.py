from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ai_bridge import provider_auth


def _fake_manager(adapters: dict[str, MagicMock]) -> MagicMock:
    manager = MagicMock()
    manager.get_adapter.side_effect = lambda name: adapters[name]
    return manager


@pytest.mark.asyncio
async def test_get_logged_in_map_queries_every_provider() -> None:
    adapters = {
        "gemini": MagicMock(is_logged_in=AsyncMock(return_value=True)),
        "chatgpt": MagicMock(is_logged_in=AsyncMock(return_value=False)),
        "deepseek": MagicMock(is_logged_in=AsyncMock(return_value=False)),
        "grok": MagicMock(is_logged_in=AsyncMock(return_value=False)),
    }
    with patch.object(provider_auth, "get_provider_manager", return_value=_fake_manager(adapters)):
        result = await provider_auth.get_logged_in_map()

    assert result == {"gemini": True, "chatgpt": False, "deepseek": False, "grok": False}


@pytest.mark.asyncio
async def test_login_reveals_the_providers_adapter() -> None:
    adapter = MagicMock(reveal=AsyncMock())
    with patch.object(provider_auth, "get_provider_manager", return_value=_fake_manager({"gemini": adapter})):
        await provider_auth.login("gemini")

    adapter.reveal.assert_awaited_once()


@pytest.mark.asyncio
async def test_logout_closes_context_and_wipes_profile_dir(tmp_path: Path) -> None:
    profile_dir = tmp_path / "gemini_profile"
    profile_dir.mkdir()
    (profile_dir / "cookie_store").write_text("fake session data")

    adapter = MagicMock(close=AsyncMock(), profile_dir=profile_dir)
    with patch.object(provider_auth, "get_provider_manager", return_value=_fake_manager({"gemini": adapter})):
        await provider_auth.logout("gemini")

    adapter.close.assert_awaited_once()
    assert not profile_dir.exists()


@pytest.mark.asyncio
async def test_logout_is_safe_when_profile_dir_never_existed(tmp_path: Path) -> None:
    adapter = MagicMock(close=AsyncMock(), profile_dir=tmp_path / "never_launched")
    with patch.object(provider_auth, "get_provider_manager", return_value=_fake_manager({"gemini": adapter})):
        await provider_auth.logout("gemini")  # should not raise
