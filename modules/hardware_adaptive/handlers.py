from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.hardware_adaptive import local_ai
from modules.hardware_adaptive.hardware_detector import detect_hardware
from modules.hardware_adaptive.model_tiers import select_tier


async def _handle_hardware_adaptive_status(_params: dict[str, Any]) -> dict[str, Any]:
    profile = detect_hardware()
    tier = select_tier(profile)
    adapter = local_ai.get_adapter()
    return {
        "hardware": dict(profile),
        "tier": tier,
        "local_model_available": adapter is not None,
        "unavailable_reason": local_ai.unavailable_reason(),
    }


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "hardware_adaptive_status",
        _handle_hardware_adaptive_status,
        dangerous=False,
        description=(
            "Report detected RAM/VRAM/CPU, the selected local model tier, and whether "
            "the local adaptive model is available (vs. falling back to ai_bridge)."
        ),
    )
