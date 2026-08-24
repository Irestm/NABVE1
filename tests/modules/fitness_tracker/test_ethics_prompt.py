from __future__ import annotations

from modules.fitness_tracker.ethics_prompt import FITNESS_ETHICS_PREFIX, compose_fitness_prompt


def test_compose_fitness_prompt_prepends_the_ethics_prefix() -> None:
    result = compose_fitness_prompt("Сколько калорий в овсянке?")

    assert result.startswith(FITNESS_ETHICS_PREFIX)
    assert result.endswith("Сколько калорий в овсянке?")


def test_ethics_prefix_mentions_the_key_ethical_rules() -> None:
    prefix = FITNESS_ETHICS_PREFIX.lower()
    assert "хорошую" in prefix and "плохую" in prefix
    assert "женщин" in prefix
    assert "врачу" in prefix or "диетолог" in prefix
