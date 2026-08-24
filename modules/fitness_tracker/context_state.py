from __future__ import annotations

from core.config import settings
from core.voice import module_context

# Thin fitness-specific wrapper over the generic core/voice/module_context.py
# primitive — entry/exit trigger phrases live in core/voice/intent.py
# (_FITNESS_START_PHRASES/is_fitness_exit_command), the same place
# _OS_AGENT_START_PHRASES/RESIGN_PHRASES already live for the other
# "in-progress mode" features, not here.
MODULE_NAME = "fitness"


def is_active() -> bool:
    return module_context.current(timeout_seconds=settings.fitness_context_timeout_seconds) == MODULE_NAME


def activate() -> None:
    module_context.activate(MODULE_NAME)


def deactivate() -> None:
    module_context.deactivate(MODULE_NAME)


def touch() -> None:
    module_context.touch()
