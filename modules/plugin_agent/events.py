from __future__ import annotations

from dataclasses import dataclass

from core.message_bus import Event


@dataclass(frozen=True)
class UnhandledQuestionAsked(Event):
    """Published by core/voice/ai_router.py whenever free text is answered
    by an AI provider instead of matching a known command — the raw signal
    plugin_agent's gap detector watches for repeated, plugin-worthy asks."""

    text: str


@dataclass(frozen=True)
class PluginCandidateReadyForReview(Event):
    """Published by modules/plugin_agent/service_layer.py::
    process_next_ready_candidate once a generated plugin's status becomes
    PENDING_REVIEW or REQUIRES_REVIEW (see modules/plugin_agent/domain.py's
    GapCandidateStatus) — i.e. there's now something a human needs to
    approve or reject (modules/plugin_agent/handlers.py's
    plugin_agent_approve/plugin_agent_reject dispatcher commands) before it
    can run for real. `requires_manual_review` mirrors whether the static
    safety scan (see plugin_generator.py::analyze_plugin_safety) flagged
    anything, so a subscriber can word its notification accordingly."""

    candidate_id: int
    plugin_name: str
    requires_manual_review: bool
