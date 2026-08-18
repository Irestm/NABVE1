from __future__ import annotations

import asyncio
import shutil

from core.browser_cookie_import import ImportResult, import_session_cookies
from core.logger import get_logger
from modules.ai_bridge.provider_manager import get_provider_manager
from modules.ai_bridge.providers import PROVIDER_ORDER

logger = get_logger(__name__)

# Real-browser domains whose session cookies actually authenticate each
# provider — includes the OAuth identity provider's own domain (google.com
# for Gemini) since that's what a from-scratch automated login gets blocked
# on; importing an already-established session sidesteps that entirely (see
# the Gemini/Quizlet investigation this was built for).
_IMPORT_DOMAINS: dict[str, list[str]] = {
    "gemini": ["google.com", "gemini.google.com"],
    "chatgpt": ["chatgpt.com", "openai.com"],
    "deepseek": ["deepseek.com"],
    "grok": ["grok.com", "x.com"],
}


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


async def import_session(provider: str) -> ImportResult:
    """Copies session cookies for `provider` from the user's own real
    Firefox/Chrome browser into this provider's automation profile — see
    core.browser_cookie_import.import_session_cookies for the mechanics and
    why (avoids a from-scratch automated login, which sites like Google
    reliably block regardless of engine/fingerprint)."""
    domains = _IMPORT_DOMAINS.get(provider)
    if not domains:
        raise ValueError(f"Unknown provider '{provider}'")
    manager = get_provider_manager()
    adapter = manager.get_adapter(provider)
    if not adapter.profile_dir.exists():
        # Bootstrap: launch once just to materialize a real profile skeleton
        # (cookies.sqlite etc.) for the writer below to write into.
        await adapter.open()
    # Never write into cookies.sqlite while a live context has it open —
    # Firefox's own WAL writes could clobber or race with ours.
    await adapter.close()
    result = await asyncio.to_thread(import_session_cookies, adapter.profile_dir, domains)
    # Reopen right away (hidden, same as any normal open() — no need to
    # surface it) so the freshly-imported cookies actually take effect —
    # is_logged_in() never launches a browser just to check (see its own
    # docstring), so without this the very next status poll would still see
    # the context as unopened and report "Гость" until something else
    # happened to open it.
    await adapter.open()
    return result


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
