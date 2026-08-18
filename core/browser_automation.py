from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


# `navigator.webdriver` is Playwright's own automation flag — both engines
# set it to `true` by default (confirmed by hand for Firefox too), and it's
# a standard, widely-checked signal bot-detection services (Cloudflare
# Turnstile in particular — confirmed to trigger a repeat "Just a moment..."
# challenge loop on quizlet.com without this) key off. Hiding it doesn't
# change what these persistent contexts actually do — the human at the
# keyboard still solves any real captcha/2FA themselves — it just stops a
# real user's own login from being misread as a bot on that one signal.
# Pass to BrowserContext.add_init_script() right after launch.
HIDE_WEBDRIVER_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def resolve_browser_launcher(playwright: Any) -> tuple[Any, dict[str, Any]]:
    """Picks which Playwright browser engine to launch for user-facing
    third-party logins (ai_bridge AI providers, Quizlet) that are driven
    through their normal web UI in a persistent, headed browser context.

    Priority, and why:
    1. Firefox — Playwright's own bundled build (`playwright install
       firefox`), independent of anything installed on the host. Confirmed
       by hand that it reaches Google's real sign-in page without the
       "This browser or app may not be secure" block that Playwright's
       default Chromium build ("Chrome for Testing") triggers every time,
       and it's meaningfully less likely to trip other sites' bot-detection
       captchas (e.g. Quizlet) the same way.
    2. A real, already-installed system Google Chrome, via Playwright's
       `channel="chrome"` — also a genuine, non-automation-flagged Chrome
       build, so it passes the same Google check. Only usable if the user
       already has Chrome installed; Playwright can't silently install it
       (unlike Firefox, that's a system package requiring root).
    3. Playwright's bundled Chromium ("Chrome for Testing") as a last
       resort, so provider login/scraping still works on a machine with
       neither — just with the known block/captcha friction on sites that
       specifically flag it.
    """
    if _playwright_firefox_available(playwright):
        return playwright.firefox, {}
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        return playwright.chromium, {"channel": "chrome"}
    return playwright.chromium, {}


def _playwright_firefox_available(playwright: Any) -> bool:
    try:
        return Path(playwright.firefox.executable_path).exists()
    except Exception:
        logger.debug("Could not check Playwright Firefox availability", exc_info=True)
        return False
