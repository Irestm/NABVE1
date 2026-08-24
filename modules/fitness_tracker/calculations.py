from __future__ import annotations

from modules.fitness_tracker.domain import Sex

# WHO BMI reference bands (kg/m^2) — the same numeric thresholds regardless
# of sex: BMI itself is not sex-adjusted anywhere in the standard clinical
# reference, unlike body-fat-percentage ranges (see
# get_body_fat_reference_note below, which IS sex-specific). Category labels
# are the neutral clinical terms, not everyday judgement words.
_UNDERWEIGHT_MAX = 18.5
_NORMAL_MAX = 25.0
_OVERWEIGHT_MAX = 30.0

_CATEGORY_UNDERWEIGHT = "дефицит массы тела"
_CATEGORY_NORMAL = "норма"
_CATEGORY_OVERWEIGHT = "избыточная масса тела"
_CATEGORY_OBESE = "ожирение"


def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m * height_m)


def get_bmi_category(bmi: float, sex: Sex | None = None) -> str:
    """Neutral WHO-band category label — sex is accepted for a uniform
    signature with the rest of this module's sex-aware helpers, but does not
    shift the numeric BMI bands themselves (see module docstring above)."""
    if bmi < _UNDERWEIGHT_MAX:
        return _CATEGORY_UNDERWEIGHT
    if bmi < _NORMAL_MAX:
        return _CATEGORY_NORMAL
    if bmi < _OVERWEIGHT_MAX:
        return _CATEGORY_OVERWEIGHT
    return _CATEGORY_OBESE


def get_body_fat_reference_note(sex: Sex | None) -> str:
    """A standalone, sex-aware clarification — deliberately kept separate
    from the numeric BMI helpers above so those stay simple, pure lookups.
    Reflects the ethical requirement that a higher female reference range be
    stated as normal physiology (reproductive function, fat distribution),
    never as a deviation."""
    if sex == "female":
        return (
            "У женщин физиологически нормальный референсный диапазон процента жира в организме выше, чем у "
            "мужчин — это связано с репродуктивной функцией и распределением жировой ткани, а не является "
            "отклонением от нормы."
        )
    if sex == "male":
        return (
            "У мужчин референсный диапазон процента жира в организме ниже, чем у женщин, — это обусловлено "
            "физиологическими различиями, а не является показателем лучшей формы."
        )
    return (
        "Референсный диапазон процента жира в организме физиологически различается между мужчинами и "
        "женщинами — это норма, а не отклонение."
    )
