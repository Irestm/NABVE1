from __future__ import annotations

import shutil

from core.logger import get_logger
from modules.ai_bridge.provider_manager import get_provider_manager
from modules.ai_bridge.providers import PROVIDER_ORDER

logger = get_logger(__name__)


async def get_logged_in_map() -> dict[str, bool]:
    """Per-provider login status for the settings UI's provider cards.
    Never launches a browser just to check — a provider whose session isn't
    already open honestly reports "Гость" rather than paying for a full
    launch on every status poll (see BrowserProviderAdapter.is_logged_in)."""
    manager = get_provider_manager()
    result: dict[str, bool] = {}
    for name in PROVIDER_ORDER:
        result[name] = await manager.get_adapter(name).is_logged_in()
    return result


async def login(provider: str) -> None:
    """Reveals the provider's browser window (launching it headed on the
    real screen if it wasn't open yet) so the user can log in themselves,
    directly on the provider's own site — Jarvis never asks for or stores
    third-party AI provider passwords. Once logged in, the persistent
    browser profile (modules.ai_bridge.providers.base's
    launch_persistent_context) keeps the session for future runs."""
    manager = get_provider_manager()
    await manager.get_adapter(provider).reveal()


async def logout(provider: str) -> None:
    """Full session reset: closes the browser context (if open) and wipes
    its persistent profile directory, so the next launch starts as a fresh
    guest session — there's no per-provider "log out" UI action reliable
    enough to automate generically across four different chat UIs."""
    manager = get_provider_manager()
    adapter = manager.get_adapter(provider)
    await adapter.close()
    if adapter.profile_dir.exists():
        shutil.rmtree(adapter.profile_dir, ignore_errors=True)
    logger.info("Reset %s browser session to guest (profile directory cleared)", provider)
