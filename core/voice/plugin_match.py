from __future__ import annotations

from core.logger import get_logger
from core.voice.intent import Command

logger = get_logger(__name__)


def match_plugin_command(text: str) -> Command | None:
    """Shared by core/voice/pipeline.py (live mic loop) and
    core/voice/web_pipeline.py (phone/browser thin client): tries to match
    `text` against a user-installed plugin's trigger patterns (see
    modules.plugin_agent.plugin_loader), used as the step between the
    built-in rule-based parser (interpret()) and the AI classifier. Import
    of plugin_loader is lazy and wrapped since the plugin system is
    optional machinery, not a hard dependency of the voice pipeline — a
    broken/missing plugin loader degrades to "no plugin match" rather than
    taking down command handling."""
    try:
        from modules.plugin_agent.plugin_loader import match_command
    except Exception:
        logger.warning("Plugin loader unavailable, skipping plugin command match", exc_info=True)
        return None
    name = match_command(text)
    if name is None:
        return None
    return Command(name=name, params={"raw_text": text})
