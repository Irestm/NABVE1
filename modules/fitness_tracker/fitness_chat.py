from __future__ import annotations

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from core.voice.fact_extraction import extract_facts
from modules.ai_bridge.api_providers import get_claude_adapter, get_gemini_adapter
from modules.fitness_tracker import announce, service_layer
from modules.fitness_tracker.ethics_prompt import compose_fitness_prompt
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_RECENT_MEALS_IN_SUMMARY = 3
_RECENT_GOALS_IN_SUMMARY = 3

_hint_shown = False


class FitnessChatError(Exception):
    pass


def reset_api_key_hint() -> None:
    """Called when the fitness voice context activates (see
    core/voice/pipeline.py) so the hint below can be offered again on the
    next "conversation" — a resumed context, not a resumed process."""
    global _hint_shown
    _hint_shown = False


def _maybe_api_key_hint(language: str) -> str | None:
    """Once per activation of the fitness context (see reset_api_key_hint),
    and only when the user has no own Gemini/Claude key configured — a
    configured key already gives the more accurate answers this hint is
    suggesting, so mentioning it would be noise."""
    global _hint_shown
    if _hint_shown:
        return None
    if get_gemini_adapter() is not None or get_claude_adapter() is not None:
        return None
    _hint_shown = True
    return announce.api_key_hint_text(language)


def build_context_summary() -> str | None:
    """Short "what we currently know" block injected into the chat prompt —
    current bio profile, active (not yet achieved) goals, and the last
    few logged meals. None when there's nothing recorded yet, so the prompt
    doesn't carry an empty/meaningless section for a brand-new user."""
    parts: list[str] = []

    profile = service_layer.get_current_bio_profile()
    if profile is not None:
        details: list[str] = []
        if profile.sex is not None:
            details.append(f"пол {profile.sex}")
        if profile.age is not None:
            details.append(f"возраст {profile.age:g} лет")
        if profile.height_cm is not None:
            details.append(f"рост {profile.height_cm:g} см")
        if profile.weight_kg is not None:
            details.append(f"вес {profile.weight_kg:g} кг")
        if profile.bmi is not None:
            details.append(f"ИМТ {profile.bmi:.1f}")
        if details:
            parts.append("Текущие показатели пользователя: " + ", ".join(details) + ".")

    active_goals = [goal for goal in service_layer.list_goals() if goal.achieved_at is None]
    if active_goals:
        descriptions = "; ".join(goal.description for goal in active_goals[:_RECENT_GOALS_IN_SUMMARY])
        parts.append(f"Активные цели пользователя: {descriptions}.")

    recent_meals = service_layer.list_meals(limit=_RECENT_MEALS_IN_SUMMARY)
    if recent_meals:
        descriptions = "; ".join(
            f"{meal.description}" + (f" (~{meal.estimated_calories:g} ккал)" if meal.estimated_calories else "")
            for meal in recent_meals
        )
        parts.append(f"Недавние приёмы пищи: {descriptions}.")

    return " ".join(parts) if parts else None


def save_important_fact(key: str, value: str) -> None:
    """Same modules.user_profile persistent-fact mechanism the rest of the
    app uses for ongoing memory, tagged with a "fitness_" key prefix (the
    same convention modules.user_profile.service_layer.save_about_me
    already uses for its own "about_" prefix) so this doesn't get mixed up
    with facts learned outside the fitness context."""
    profile_service_layer.record_episodic_fact(ProfileUnitOfWork(), f"fitness_{key}", value)


def _learn_from_chat(text: str, language: str) -> None:
    """Runs the same rule-based extractor core/voice/pipeline.py's
    _learn_facts uses on every ordinary utterance, but tags whatever it
    finds as fitness-sourced (see save_important_fact) — best-effort, never
    allowed to break the actual chat answer if it fails."""
    try:
        for fact in extract_facts(text, language):
            save_important_fact(fact.key, fact.value)
    except Exception:
        logger.exception("Fitness chat fact extraction failed")


async def answer_question(text: str, language: str = "ru") -> str:
    """Answers a free-text fitness question using the current AI provider
    chain (core.ai_adapter_chain.candidate_chain — the same complexity-aware
    routing every other AI-backed module in this app uses), with the
    ethical prefix (modules.fitness_tracker.ethics_prompt) always applied
    and the user's own recorded fitness context injected for a personalized,
    non-directive answer. Raises FitnessChatError if every adapter fails."""
    _learn_from_chat(text, language)

    summary = build_context_summary()
    prompt_body = f"{summary}\n\nВопрос пользователя: {text}" if summary else text
    prompt = compose_fitness_prompt(prompt_body)

    last_error: Exception | None = None
    for adapter in candidate_chain(text):
        try:
            reply = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            last_error = exc
            logger.warning("Fitness chat adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        stripped = reply.strip()
        if stripped:
            hint = _maybe_api_key_hint(language)
            return f"{stripped} {hint}" if hint else stripped

    logger.error("All AI adapters failed to answer a fitness chat question: %s", last_error, exc_info=last_error)
    raise FitnessChatError("Не удалось получить ответ — все AI-адаптеры недоступны.")
