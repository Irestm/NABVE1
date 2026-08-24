from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from core.models import CommandDescriptor
from core.ports import PromptProviderPort
from core.voice.intent import Command
from core.voice.sound_effects import BREATH_MARKER
from modules.ai_bridge.intent_classifier import classify
from modules.plugin_agent.events import UnhandledQuestionAsked
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import BREATH_EFFECT_KEY
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_MEMORY_CONTEXT_FACT_BUDGET = 10

# Only ever appended for a genuine free-text answer (see
# _with_memory_context below) — never for intent_classifier's JSON-only
# classification prompt, which lives entirely in a different module and
# never touches this function. Telling the model about the marker on every
# single prompt, including ones that must return strict JSON, would risk it
# turning up somewhere that breaks parsing.
_BREATH_MARKER_INSTRUCTION = (
    f"Если в этом конкретном ответе уместна многозначительная пауза — как будто ты затягиваешься "
    f"сигаретой и выдыхаешь дым, для эффекта веса или философской глубины перед важной мыслью — "
    f"вставь в тексте ровно в этом месте маркер {BREATH_MARKER} (и больше нигде в ответе). Если "
    f"пауза не нужна — просто не пиши маркер вообще."
)

# A small local quantized model doesn't reliably follow soft frequency
# guidance like "use rarely" once a special token is offered as an option
# at all - in practice it started reaching for it on nearly every answer.
# Rather than trust the model's own restraint, the option itself is only
# ever offered on a fraction of prompts, so "always/every answer" is
# structurally impossible regardless of how the model behaves once it does
# see the instruction.
_BREATH_MARKER_OFFER_PROBABILITY = 0.15

_MIN_ANSWER_LENGTH = 2
# A word repeated this many times in a row is treated as a degenerate
# generation loop rather than a real answer — a known small-quantized-model
# failure mode (e.g. Qwen2.5-3B under an aggressive quantization), not
# something the cloud ai_bridge providers exhibit, but cheap enough to check
# for every adapter's output regardless of source.
_DEGENERATE_REPEAT_RUN = 8


def is_degenerate_answer(text: str) -> bool:
    """True if `text` looks like a broken generation (empty, or stuck
    repeating the same word) rather than an actual answer worth showing or
    speaking to the user."""
    stripped = text.strip()
    if len(stripped) < _MIN_ANSWER_LENGTH:
        return True

    words = stripped.lower().split()
    longest_run = 1
    current_run = 1
    for previous, current in zip(words, words[1:]):
        if current == previous:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 1
    return longest_run >= _DEGENERATE_REPEAT_RUN


def _with_memory_context(text: str) -> str:
    """Prepends a short "what we know about the user" block — the same
    place SYSTEM_PROMPT_PREFIX is centrally applied for tone (see
    modules/ai_bridge/system_prompt.py), just one layer up, since here it's
    per-request content rather than a fixed instruction. Only called for
    text that's actually going to a model as a question to answer, not for
    command classification, so cached facts can't skew intent matching.

    Also where the breath-marker instruction (see core/voice/tts.py's
    marker-splicing) gets appended, gated on the same profile setting the
    settings-panel checkbox writes — no point telling the model about a
    marker core/voice/tts.py won't be looking for anyway."""
    facts = profile_service_layer.get_context_facts(ProfileUnitOfWork(), budget=_MEMORY_CONTEXT_FACT_BUDGET)
    summary = profile_service_layer.format_context_summary(facts)
    prompt = f"{summary}\n\n{text}" if summary else text

    breath_enabled = profile_service_layer.get_fact(ProfileUnitOfWork(), BREATH_EFFECT_KEY) == "1"
    if breath_enabled and random.random() < _BREATH_MARKER_OFFER_PROBABILITY:
        prompt = f"{prompt}\n\n{_BREATH_MARKER_INSTRUCTION}"

    return prompt


async def _record_gap_candidate(text: str, bus: MessageBus) -> None:
    """Publishes a free-text question that's about to be answered by a model
    as-is, so modules.plugin_agent can notice repeated asks and suggest
    generating a plugin for it. Decoupled via the message bus (rather than
    importing plugin_agent directly) so this module doesn't need to know
    that subscriber exists, and a failing subscriber can't break the actual
    answer flow — core/message_bus.py already isolates handler errors."""
    await bus.publish(UnhandledQuestionAsked(text=text))


def _candidate_adapters(text: str) -> list[PromptProviderPort]:
    """Thin wrapper kept for this module's own call sites/tests — the actual
    complexity-aware ordering (own Gemini/Claude keys included) now lives in
    core.ai_adapter_chain.candidate_chain, so every other caller of that
    module gets the same behavior, not just this voice free-text path."""
    return candidate_chain(text)


async def _stream_and_collect(
    adapter: PromptProviderPort, prompt_text: str, on_chunk: Callable[[str], Awaitable[None]]
) -> str:
    pieces: list[str] = []
    async for chunk in adapter.stream_prompt(prompt_text):  # type: ignore[attr-defined]
        pieces.append(chunk)
        await on_chunk(chunk)
    return "".join(pieces)


async def resolve_free_text(
    text: str,
    commands: list[CommandDescriptor],
    *,
    on_stream_chunk: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[Command | None, str | None]:
    """Classifies free text (from voice or a phone/browser text query) that
    didn't match any rule-based command pattern, and either resolves it to a
    command to dispatch, or answers it directly. Returns
    (command, answer): exactly one is set, or both are None if nothing usable
    came back (caller should say/show "didn't understand").

    `on_stream_chunk`, if given, is awaited with each text delta as soon as
    it's produced whenever the winning adapter supports streaming (currently
    only the local model — see modules.hardware_adaptive.local_ai) — used by
    the live voice pipeline to start speaking the reply before the whole
    thing has finished generating. The returned `answer` is still the full,
    concatenated text either way, so callers that don't pass this (e.g. the
    phone/browser HTTP endpoint, which needs the complete text up front to
    synthesize one WAV file) are unaffected."""
    adapters = _candidate_adapters(text)

    result = await classify(text, commands, adapters[0])
    if result.matched_command is not None:
        return Command(name=result.matched_command, params=dict(result.params)), None

    if not result.is_direct_question:
        return None, None

    await _record_gap_candidate(text, message_bus)

    prompt_text = await asyncio.to_thread(_with_memory_context, text)

    last_error: Exception | None = None
    for adapter in adapters:
        try:
            if on_stream_chunk is not None and hasattr(adapter, "stream_prompt"):
                answer = await _stream_and_collect(adapter, prompt_text, on_stream_chunk)
            else:
                answer = await adapter.send_prompt(prompt_text, fast_mode=True)
                if is_degenerate_answer(answer):
                    logger.warning(
                        "AI adapter '%s' returned a degenerate answer, trying next", adapter.name
                    )
                    continue
            return None, answer
        except Exception as exc:
            last_error = exc
            logger.warning(
                "AI adapter '%s' failed to answer, trying next: %s", adapter.name, exc, exc_info=exc
            )

    logger.error("All AI adapters failed to answer free text: %s", last_error, exc_info=last_error)
    return None, None
