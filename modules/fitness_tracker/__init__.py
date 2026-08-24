from __future__ import annotations

# No register_commands here — same reasoning as modules.os_agent: this
# module has no CommandDispatcher-registered command of its own. Its voice
# commands ("fitness_activate_context"/"fitness_utterance") are resolved
# and handled entirely inside core/voice/pipeline.py (see
# _resolve_active_fitness_context_utterance/_resolve_fitness_utterance),
# and its REST endpoints (core/main.py's /api/fitness/*) call straight into
# modules.fitness_tracker.service_layer/meal_analyzer/fitness_chat, not
# through the dispatcher either.
