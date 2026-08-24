from __future__ import annotations

import pytest

from modules.fitness_tracker import calculations

_JUDGEMENTAL_WORDS = ("толст", "худ", "плохо", "хорошо", "жирн", "уродл")


def test_calculate_bmi() -> None:
    assert calculations.calculate_bmi(weight_kg=78.0, height_cm=180.0) == pytest.approx(24.07, abs=0.01)


@pytest.mark.parametrize(
    "bmi, expected",
    [
        (17.0, "дефицит массы тела"),
        (18.5, "норма"),
        (22.0, "норма"),
        (24.99, "норма"),
        (25.0, "избыточная масса тела"),
        (29.99, "избыточная масса тела"),
        (30.0, "ожирение"),
        (35.0, "ожирение"),
    ],
)
def test_get_bmi_category_boundaries(bmi: float, expected: str) -> None:
    assert calculations.get_bmi_category(bmi) == expected


def test_get_bmi_category_is_the_same_across_sexes() -> None:
    assert calculations.get_bmi_category(22.0, "male") == calculations.get_bmi_category(22.0, "female")


@pytest.mark.parametrize("bmi", [17.0, 22.0, 27.0, 32.0])
def test_get_bmi_category_never_uses_judgemental_words(bmi: float) -> None:
    category = calculations.get_bmi_category(bmi).lower()
    assert not any(word in category for word in _JUDGEMENTAL_WORDS)


def test_get_body_fat_reference_note_frames_female_range_as_normal() -> None:
    note = calculations.get_body_fat_reference_note("female").lower()
    assert "выше" in note
    assert "не является отклонением" in note


def test_get_body_fat_reference_note_never_uses_judgemental_words() -> None:
    for sex in ("male", "female", None):
        note = calculations.get_body_fat_reference_note(sex).lower()
        assert not any(word in note for word in _JUDGEMENTAL_WORDS)
