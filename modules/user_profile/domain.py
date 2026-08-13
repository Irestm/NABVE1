from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# Reserved keys the service layer uses for its own bookkeeping (onboarding
# gate) and for onboarding answers that other modules need to look up by a
# stable name (communication style feeds core/voice/tts.py's prosody and
# modules/ai_bridge/system_prompt.py's tone; assistant name feeds the system
# prompt too) — stored as ordinary facts so they ride along with the same
# encrypted table/backup/export path as everything else instead of needing a
# second store.
ONBOARDING_COMPLETE_KEY = "__onboarding_complete__"
ASSISTANT_NAME_KEY = "assistant_name"
COMMUNICATION_STYLE_KEY = "communication_style"
# The phrase that pauses/resumes the voice loop — see
# modules/user_profile/onboarding.py._ask_stop_word and
# core/voice/pipeline.py._wait_for_wake_or_pause.
STOP_WORD_KEY = "stop_word"
# "1"/"0" (stored as a string, like ONBOARDING_COMPLETE_KEY) — whether a
# short synthesized breath/inhale sound plays before every spoken reply.
# See core/voice/sound_effects.py and core/voice/tts.py.
BREATH_EFFECT_KEY = "breath_effect_enabled"
# Free-text "about me" blob from the settings panel's Профиль tab, plus the
# structured facts service_layer.save_about_me pulls out of it via
# core/voice/fact_extraction.py's rule-based extractor — see that function
# for why extraction is duplicated here instead of only on spoken utterances.
ABOUT_ME_KEY = "about_me"

# Episodic facts older than this are eligible for eviction even if the total
# count is under the cap — see service_layer.evict_stale_facts.
EPISODIC_TTL_DAYS = 30
# Hard cap on episodic rows; once exceeded, lowest importance*recency score
# is evicted first. Core facts (onboarding answers, explicit profile_set)
# are exempt — this is the "remember the main things, forget the noise"
# behavior requested for the assistant's working memory.
EPISODIC_MAX_FACTS = 50


class FactCategory(str, Enum):
    # Deliberately captured (onboarding interview, explicit `profile_set`).
    # Never auto-evicted.
    CORE = "core"
    # Picked up incidentally during normal conversation. Bounded and
    # time-limited — see EPISODIC_TTL_DAYS / EPISODIC_MAX_FACTS.
    EPISODIC = "episodic"


@dataclass
class ProfileFact:
    key: str
    value: str
    category: FactCategory = FactCategory.CORE
    importance: float = 1.0
    learned_at: datetime = None  # type: ignore[assignment]
    last_used_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc)
        if self.learned_at is None:
            self.learned_at = now
        if self.last_used_at is None:
            self.last_used_at = self.learned_at

    def touch(self) -> None:
        self.last_used_at = datetime.now(timezone.utc)

    def retention_score(self) -> float:
        """Lower means "forget me sooner". Combines how important the fact
        was judged to be with how recently it was last relevant, so a
        frequently-referenced low-importance fact can outlive a
        never-reused higher-importance one, and vice versa."""
        age_hours = max(
            (datetime.now(timezone.utc) - self.last_used_at).total_seconds() / 3600.0, 0.0
        )
        recency_weight = 1.0 / (1.0 + age_hours / 24.0)
        return self.importance * recency_weight
