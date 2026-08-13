from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.logger import get_logger
from core.voice.fact_extraction import extract_facts
from modules.user_profile.domain import (
    ABOUT_ME_KEY,
    EPISODIC_MAX_FACTS,
    EPISODIC_TTL_DAYS,
    ONBOARDING_COMPLETE_KEY,
    FactCategory,
    ProfileFact,
)
from modules.user_profile.uow import ProfileUnitOfWork

# extract_facts's patterns are keyed by language; "about me" text from the
# settings panel has no separate language selector, so every supported
# language is tried and whatever matches is kept - the patterns are narrow
# fixed phrases ("meня зовут"/"my name is"/...), so trying all three costs
# nothing on the common case where only one actually matches anything.
_ABOUT_ME_LANGUAGES = ("ru", "uk", "en")

logger = get_logger(__name__)


def set_fact(
    uow: ProfileUnitOfWork,
    key: str,
    value: str,
    *,
    category: FactCategory = FactCategory.CORE,
    importance: float = 1.0,
) -> None:
    """Deliberately-captured fact: onboarding answers and explicit
    `profile_set` calls. Defaults to CORE, i.e. never auto-evicted."""
    with uow:
        uow.facts.add(ProfileFact(key=key, value=value, category=category, importance=importance))
        uow.commit()
    logger.info("Stored profile fact key='%s' category=%s", key, category.value)


def save_about_me(uow: ProfileUnitOfWork, text: str) -> list[str]:
    """Stores the settings panel's free-text "О себе" field verbatim under
    ABOUT_ME_KEY, then runs it through the same rule-based extractor used on
    spoken utterances (core/voice/fact_extraction.py) so phrasing like "меня
    зовут Даниил, я работаю программистом" also lands as individual
    core.name/core.work facts the AI prompt context can address directly,
    not just as one opaque blob. Returns the extracted fact keys (each
    prefixed "about_") for the caller to report back to the user."""
    set_fact(uow, ABOUT_ME_KEY, text, category=FactCategory.CORE, importance=1.0)

    extracted_keys: list[str] = []
    seen_keys: set[str] = set()
    for language in _ABOUT_ME_LANGUAGES:
        for fact in extract_facts(text, language):
            key = f"about_{fact.key}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            extracted_keys.append(key)
            set_fact(uow, key, fact.value, category=FactCategory.CORE, importance=1.0)
    return extracted_keys


def record_episodic_fact(uow: ProfileUnitOfWork, key: str, value: str, importance: float = 0.4) -> None:
    """Fact picked up incidentally during normal conversation (see
    core/voice/pipeline.py's rule-based extractor). Bounded — every write
    triggers an eviction pass so this behaves like a cache, not a growing
    log."""
    set_fact(uow, key, value, category=FactCategory.EPISODIC, importance=importance)
    evicted = evict_stale_facts(uow)
    if evicted:
        logger.info("Evicted %d stale episodic fact(s) after learning '%s'", evicted, key)


def get_fact(uow: ProfileUnitOfWork, key: str) -> str | None:
    with uow:
        fact = uow.facts.get(key)
        if fact is None:
            return None
        # Being asked-about is itself a signal the fact is still relevant —
        # reinforces it against eviction the same way record_episodic_fact's
        # eviction pass scores by last_used_at.
        uow.facts.touch(key)
        uow.commit()
        return fact.value


def delete_fact(uow: ProfileUnitOfWork, key: str) -> bool:
    with uow:
        deleted = uow.facts.delete(key)
        uow.commit()
    if deleted:
        logger.info("Deleted profile fact key='%s'", key)
    return deleted


# `forget` is the explicit-user-request entry point (voice: "forget X" /
# `profile_forget` command) — same operation as delete_fact, named
# separately so call sites read intentionally rather than looking like
# internal bookkeeping.
forget = delete_fact


def list_keys(uow: ProfileUnitOfWork) -> list[str]:
    with uow:
        return uow.facts.list_keys()


def is_onboarded(uow: ProfileUnitOfWork) -> bool:
    with uow:
        return uow.facts.get(ONBOARDING_COMPLETE_KEY) is not None


def complete_onboarding(uow: ProfileUnitOfWork) -> None:
    set_fact(uow, ONBOARDING_COMPLETE_KEY, "1", category=FactCategory.CORE, importance=1.0)


def get_context_facts(uow: ProfileUnitOfWork, budget: int = 10) -> list[ProfileFact]:
    """Facts worth injecting into an AI prompt as "what we know about the
    user", most relevant first. Core facts (onboarding + explicit sets) are
    prioritized; remaining budget is filled with the highest-scoring
    episodic facts. Bounded by `budget` so prompts stay small regardless of
    how much has been learned over time."""
    with uow:
        core_facts = [
            fact
            for fact in uow.facts.list_by_category(FactCategory.CORE)
            if fact.key != ONBOARDING_COMPLETE_KEY
        ]
        episodic_facts = uow.facts.list_by_category(FactCategory.EPISODIC)

    core_facts.sort(key=lambda f: f.retention_score(), reverse=True)
    episodic_facts.sort(key=lambda f: f.retention_score(), reverse=True)

    selected = core_facts[:budget]
    remaining = budget - len(selected)
    if remaining > 0:
        selected.extend(episodic_facts[:remaining])
    return selected


def format_context_summary(facts: list[ProfileFact]) -> str | None:
    if not facts:
        return None
    parts = [f"{fact.key}: {fact.value}" for fact in facts]
    return "Известно о пользователе: " + "; ".join(parts) + "."


def evict_stale_facts(uow: ProfileUnitOfWork) -> int:
    """Deletes expired episodic facts, then trims anything still over the
    cap by lowest retention_score. Returns the number of facts removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=EPISODIC_TTL_DAYS)
    removed = 0
    with uow:
        episodic_facts = uow.facts.list_by_category(FactCategory.EPISODIC)
        survivors: list[ProfileFact] = []
        for fact in episodic_facts:
            if fact.last_used_at < cutoff:
                uow.facts.delete(fact.key)
                removed += 1
            else:
                survivors.append(fact)

        if len(survivors) > EPISODIC_MAX_FACTS:
            survivors.sort(key=lambda f: f.retention_score(), reverse=True)
            for fact in survivors[EPISODIC_MAX_FACTS:]:
                uow.facts.delete(fact.key)
                removed += 1

        uow.commit()
    return removed
