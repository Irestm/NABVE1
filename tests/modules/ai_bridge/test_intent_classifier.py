from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.models import CommandDescriptor
from modules.ai_bridge import intent_classifier


def _commands() -> list[CommandDescriptor]:
    return [
        CommandDescriptor(name="set_volume", dangerous=False, description="Set system volume (percent)"),
        CommandDescriptor(name="open_app", dangerous=False, description="Open an application"),
    ]


@pytest.mark.asyncio
async def test_classify_accepts_a_near_verbatim_command_name_without_calling_the_provider() -> None:
    manager = AsyncMock()

    result = await intent_classifier.classify("set volume", _commands(), manager)

    assert result.matched_command == "set_volume"
    assert result.is_direct_question is False
    manager.send_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_classify_asks_the_provider_when_no_direct_match() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": "open_app", "params": {"target": "spotify"}, "is_direct_question": false}'
    )

    result = await intent_classifier.classify("запусти спотифай", _commands(), manager)

    assert result.matched_command == "open_app"
    assert result.params == {"target": "spotify"}
    assert result.is_direct_question is False


@pytest.mark.asyncio
async def test_classify_treats_unparseable_json_as_a_question() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = "not json at all"

    result = await intent_classifier.classify("какая погода в москве", _commands(), manager)

    assert result.matched_command is None
    assert result.is_direct_question is True


@pytest.mark.asyncio
async def test_classify_rejects_a_command_name_the_model_invented() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": "delete_everything", "params": {}, "is_direct_question": false}'
    )

    result = await intent_classifier.classify("привет", _commands(), manager)

    assert result.matched_command is None


@pytest.mark.asyncio
async def test_classify_falls_back_to_a_question_when_the_provider_raises() -> None:
    manager = AsyncMock()
    manager.send_prompt.side_effect = RuntimeError("no provider logged in")

    result = await intent_classifier.classify("привет", _commands(), manager)

    assert result.matched_command is None
    assert result.is_direct_question is True
    # Regression: a provider error must be distinguishable from a genuine
    # "the model looked at this and decided it's a question" verdict — see
    # ai_router.resolve_free_text, which uses this flag to avoid routing a
    # failed classification into a conversational answer that could
    # hallucinate a fake "done" for an unexecuted command.
    assert result.classification_failed is True


@pytest.mark.asyncio
async def test_classify_marks_unparseable_output_as_classification_failed() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = "not json at all"

    result = await intent_classifier.classify("какая погода в москве", _commands(), manager)

    assert result.classification_failed is True


@pytest.mark.asyncio
async def test_classify_does_not_mark_a_genuine_question_verdict_as_failed() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": null, "params": {}, "is_direct_question": true}'
    )

    result = await intent_classifier.classify("какая погода в москве", _commands(), manager)

    assert result.is_direct_question is True
    assert result.classification_failed is False


def test_build_prompt_omits_context_section_when_no_hint_given() -> None:
    prompt = intent_classifier._build_prompt("какая погода", _commands())

    assert "Контекст этого же разговора" not in prompt


def test_build_prompt_includes_context_hint_when_given() -> None:
    hint = "Пользователь спросил про погоду в Киеве на завтра."
    prompt = intent_classifier._build_prompt("а сегодня какая была", _commands(), hint)

    assert hint in prompt
    assert "Контекст этого же разговора" in prompt
    # The hint must come before the actual utterance being classified, not
    # buried after the instructions.
    assert prompt.index(hint) < prompt.index("а сегодня какая была")


def test_build_prompt_context_section_includes_a_few_shot_example() -> None:
    # Regression, found live: a plain prose instruction ("use the context
    # to fill in missing parameters") was unreliable on its own - even a
    # weak model ignored a real "а сегодня какая была?" follow-up and
    # answered "just a question". A worked example of the same pattern
    # (with a *different* city/day, so it can't be mistaken for the real
    # answer being spelled out) is what actually fixed it - this asserts
    # the example stays in the prompt, not just the bare instruction.
    prompt = intent_classifier._build_prompt(
        "а сегодня какая была", _commands(), "Пользователь спросил про погоду в Киеве на завтра."
    )

    assert "Одесса" in prompt  # the example's deliberately-different city
    assert "day_after_tomorrow" in prompt
    # Regression: a weather-only example didn't generalize live to a real
    # non-weather follow-up ("ладно, на 50" after a volume command) — a
    # second example from a different command family is what fixed it.
    assert "change_volume" in prompt
    assert "set_volume" in prompt


@pytest.mark.asyncio
async def test_classify_passes_context_hint_into_the_prompt_sent_to_the_provider() -> None:
    # Regression: an elliptical follow-up ("а сегодня какая была?" - no
    # "погода" at all) has nothing rule-based or a fresh AI call without
    # context could reasonably resolve on its own - the previous exchange
    # must actually reach the provider prompt, not just exist as a
    # parameter nobody reads.
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": "weather_get", "params": {"city": "Киев", "when": "today"}, '
        '"is_direct_question": false}'
    )

    result = await intent_classifier.classify(
        "а сегодня какая была",
        [CommandDescriptor(name="weather_get", dangerous=False, description="Погода (city, when)")],
        manager,
        context_hint="Пользователь спросил про погоду в Киеве на завтра.",
    )

    assert result.matched_command == "weather_get"
    assert result.params == {"city": "Киев", "when": "today"}
    sent_prompt = manager.send_prompt.call_args[0][0]
    assert "Пользователь спросил про погоду в Киеве на завтра." in sent_prompt
