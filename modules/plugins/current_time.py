from __future__ import annotations

from datetime import datetime
from typing import Any

from modules.plugin_agent.plugin_interface import PluginBase


class CurrentTimePlugin(PluginBase):
    name = "plugin_current_time"
    description = "Reports the current local date and time."
    trigger_patterns = [
        "который час",
        "какое сегодня число",
        "what time is it",
        "what's the date today",
    ]

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now()
        return {
            "iso": now.isoformat(),
            "human": now.strftime("%Y-%m-%d %H:%M:%S"),
            "message": f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%d.%m.%Y')}.",
        }


plugin = CurrentTimePlugin()
