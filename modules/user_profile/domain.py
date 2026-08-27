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
# The phrase that pauses/resumes the voice loop — set via
# frontend/src/components/SettingsPanel.tsx's Профиль tab, read by
# core/voice/pipeline.py._wait_for_wake_or_pause.
STOP_WORD_KEY = "stop_word"
# Custom activation phrase, added to core/voice/wake_word.py's
# DEFAULT_WAKE_PHRASES rather than replacing them — see
# core/voice/wake_word.py.resolve_wake_phrases, the only reader, and
# core/voice/pipeline.py._wait_for_wake_or_pause, which re-reads this fact
# every pass for the same reason STOP_WORD_KEY does (see its own comment).
WAKE_PHRASE_KEY = "wake_phrase"
# "1"/"0" — whether launch_app custom commands (modules/custom_commands)
# require spoken yes/no confirmation before running, and text_instruction
# custom commands require it before their stored instruction is substituted
# back into the normal command pipeline. Off by default: these are the
# user's own personal shortcuts authored through their own settings UI, not
# third-party input, so gating every use behind a confirmation prompt would
# defeat the point of a quick voice shortcut for most users. See
# modules/custom_commands/dispatcher.py's _requires_confirmation.
CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY = "custom_commands_require_confirmation"
# "1"/"0" (stored as a string, like ONBOARDING_COMPLETE_KEY) — whether a
# short synthesized breath/inhale sound plays before every spoken reply.
# See core/voice/sound_effects.py and core/voice/tts.py.
BREATH_EFFECT_KEY = "breath_effect_enabled"
# "1"/"0" — whether a configurable silence is prepended before playback
# starts. Paired with DELAY_SECONDS_KEY (stringified float, seconds). See
# core/voice/tts_effects.py and core/voice/tts.py.
DELAY_EFFECT_ENABLED_KEY = "delay_effect_enabled"
DELAY_SECONDS_KEY = "delay_seconds"
# "none" | "tunnel" | "robotic" — mutually exclusive voice-distortion effect
# applied to the whole synthesized reply. See core/voice/tts_effects.py.
VOICE_FX_MODE_KEY = "voice_fx_mode"
# Stringified int 0-100 — the assistant's own TTS output gain, independent
# of the OS mixer level (core/dispatcher.py's set_volume/change_volume).
# See core/voice/tts.py's get_assistant_volume/set_assistant_volume.
ASSISTANT_VOLUME_KEY = "assistant_volume"
# Free-text "about me" blob from the settings panel's Профиль tab, plus the
# structured facts service_layer.save_about_me pulls out of it via
# core/voice/fact_extraction.py's rule-based extractor — see that function
# for why extraction is duplicated here instead of only on spoken utterances.
ABOUT_ME_KEY = "about_me"
# Optional explicit home-city override for modules/weather, checked before
# its own IP-geolocation fallback (see modules/weather/service_layer.py) -
# not surfaced in a dedicated Settings field yet, but settable right now
# through the same generic profile_get/profile_set commands STOP_WORD_KEY
# uses (e.g. "запомни, город Одесса" via ABOUT_ME_KEY's own extractor, or
# profile_set directly).
CITY_KEY = "city"
# "male" | "female" — which gendered form of address (сэр/мэм) the assistant
# uses. Currently drives core/voice/confirmation_phrase.py's
# get_confirmation_phrase() only. See modules/user_profile/handlers.py's
# generic profile_set/profile_get for how the settings UI reads/writes this
# like any other fact.
GENDER_KEY = "gender"
DEFAULT_GENDER = "male"
# "1"/"0" — whether a short Jarvis-style confirmation phrase ("Да, сэр"/"Да,
# мэм", chosen by core/voice/confirmation_phrase.get_confirmation_phrase) is
# spoken before executing any recognized command (system command, custom
# command, plugin, Figma/Blender command, ...) — not before plain
# conversational answers. See core/voice/pipeline.py's _handle_command.
CONFIRMATION_PHRASE_ENABLED_KEY = "confirmation_phrase_enabled"

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
