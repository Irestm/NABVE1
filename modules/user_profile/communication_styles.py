from __future__ import annotations

from dataclasses import dataclass

from modules.user_profile import service_layer
from modules.user_profile.domain import COMMUNICATION_STYLE_KEY
from modules.user_profile.uow import ProfileUnitOfWork


@dataclass(frozen=True)
class CommunicationStyle:
    key: str
    label: str
    # Appended to core.config.SYSTEM_PROMPT_PREFIX (see
    # modules/ai_bridge/system_prompt.py) to shape wording/tone.
    prompt_fragment: str
    # Fed to core/voice/tts.py's prosody step: >1.0 speeds up and raises
    # pitch, <1.0 slows down and lowers it, 1.0 is unchanged. This is a
    # simple resample-based approximation (see tts.py:_apply_prosody_rate),
    # not independent tempo/pitch control — Silero's synthesize() doesn't
    # expose real prosody parameters, so tempo and pitch move together here.
    prosody_rate: float


# Order is also the order read aloud during onboarding (see
# onboarding.py:_ask_communication_style).
COMMUNICATION_STYLES: tuple[CommunicationStyle, ...] = (
    CommunicationStyle(
        key="polite",
        label="Вежливо",
        prompt_fragment='Общайся вежливо и уважительно, обращайся на "вы".',
        prosody_rate=1.0,
    ),
    CommunicationStyle(
        key="grounded",
        label="Приземлённо",
        prompt_fragment="Общайся просто и по-свойски, без канцелярита, как обычный человек.",
        prosody_rate=1.0,
    ),
    CommunicationStyle(
        key="aggressive",
        label="Агрессивно",
        prompt_fragment="Общайся резко и напористо, без сантиментов, можно грубовато подкалывать.",
        prosody_rate=1.15,
    ),
    CommunicationStyle(
        key="calm",
        label="Спокойно",
        prompt_fragment="Общайся размеренно, спокойно и невозмутимо, не суетись.",
        prosody_rate=0.9,
    ),
    CommunicationStyle(
        key="rude",
        label="С матами",
        prompt_fragment="Общайся неформально, с использованием ненормативной лексики там, где это уместно.",
        prosody_rate=1.1,
    ),
    CommunicationStyle(
        key="friendly",
        label="Дружелюбно",
        prompt_fragment="Общайся тепло и дружелюбно, как с хорошим приятелем.",
        prosody_rate=1.05,
    ),
    CommunicationStyle(
        key="formal",
        label="Официально",
        prompt_fragment="Общайся сухо и официально, строго по делу, минимум эмоций.",
        prosody_rate=0.95,
    ),
    CommunicationStyle(
        key="humorous",
        label="С юмором",
        prompt_fragment="Общайся с лёгким юмором и иронией, где это уместно.",
        prosody_rate=1.05,
    ),
    CommunicationStyle(
        key="philosophical",
        label="Философски",
        prompt_fragment=(
            "Общайся вдумчиво и рассудительно: прежде чем ответить по существу, можешь коротко "
            "поразмышлять о более широком смысле или контексте вопроса."
        ),
        prosody_rate=0.9,
    ),
)

DEFAULT_STYLE_KEY = "polite"
# Traits are meant to be combined ("миксовать"), not just picked one at a
# time — capped at 3 so the merged prompt fragment stays short enough to
# actually follow (and doesn't just contradict itself into noise), and so
# the averaged prosody_rate below doesn't get diluted toward 1.0 by piling
# on more and more traits.
MAX_SELECTED_STYLES = 3

_STYLES_BY_KEY: dict[str, CommunicationStyle] = {style.key: style for style in COMMUNICATION_STYLES}


def get_style(key: str | None) -> CommunicationStyle:
    """The style for `key`, or the default if `key` is None or no longer
    recognized (e.g. this codebase's style list changed after the user's
    choice was persisted)."""
    if key is None:
        return _STYLES_BY_KEY[DEFAULT_STYLE_KEY]
    return _STYLES_BY_KEY.get(key, _STYLES_BY_KEY[DEFAULT_STYLE_KEY])


def parse_style_keys(raw: str | None) -> list[str]:
    """Parses the comma-joined value stored under COMMUNICATION_STYLE_KEY
    into up to MAX_SELECTED_STYLES valid, de-duplicated style keys (order
    preserved), falling back to [DEFAULT_STYLE_KEY] if `raw` is empty or
    names nothing recognized. A single bare key (no comma) — the format
    this fact was stored in before trait-mixing existed — parses the same
    way as a one-element list, so old persisted values keep working."""
    if not raw:
        return [DEFAULT_STYLE_KEY]

    seen: set[str] = set()
    keys: list[str] = []
    for candidate in raw.split(","):
        key = candidate.strip()
        if key in _STYLES_BY_KEY and key not in seen:
            seen.add(key)
            keys.append(key)
        if len(keys) == MAX_SELECTED_STYLES:
            break

    return keys or [DEFAULT_STYLE_KEY]


def combine_styles(keys: list[str]) -> CommunicationStyle:
    """Merges 1-3 styles into a single effective one: prompt fragments are
    concatenated (the model just gets all the selected instructions in
    sequence — combinations may pull against each other, e.g. "агрессивно"
    plus "официально", but that tension is exactly what "миксовать черты"
    asked for, not something to prevent) and prosody_rate is averaged, so
    stacking traits doesn't runaway to an extreme tempo the way summing
    would. A single-key list returns that style's own record unchanged."""
    selected = [_STYLES_BY_KEY[key] for key in keys if key in _STYLES_BY_KEY] or [_STYLES_BY_KEY[DEFAULT_STYLE_KEY]]
    if len(selected) == 1:
        return selected[0]

    return CommunicationStyle(
        key="+".join(style.key for style in selected),
        label=" + ".join(style.label for style in selected),
        prompt_fragment=" ".join(style.prompt_fragment for style in selected),
        prosody_rate=sum(style.prosody_rate for style in selected) / len(selected),
    )


def get_current_style() -> CommunicationStyle:
    """The (possibly merged) style chosen during onboarding or the
    personality settings panel (see
    modules.user_profile.onboarding._ask_communication_style and
    modules.user_profile.handlers.list_communication_styles), or the
    default if nothing has been chosen yet."""
    raw = service_layer.get_fact(ProfileUnitOfWork(), COMMUNICATION_STYLE_KEY)
    return combine_styles(parse_style_keys(raw))
