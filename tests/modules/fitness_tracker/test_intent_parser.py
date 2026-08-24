from __future__ import annotations

import pytest

from modules.fitness_tracker import intent_parser as ip

pytestmark = pytest.mark.filterwarnings("ignore")


# --- pure entity-extraction helpers (no model needed) -----------------------


def test_extract_number_finds_the_first_number() -> None:
    assert ip._extract_number("мой вес 78 кг") == 78.0
    assert ip._extract_number("вес 78,5 кг") == 78.5


def test_extract_number_returns_none_without_a_number() -> None:
    assert ip._extract_number("запиши мой вес") is None


def test_extract_sex_recognizes_male_and_female_stems() -> None:
    assert ip._extract_sex("я мужчина") == "male"
    assert ip._extract_sex("я парень") == "male"
    assert ip._extract_sex("я женщина") == "female"
    assert ip._extract_sex("я девушка") == "female"


def test_extract_sex_returns_none_for_unrelated_text() -> None:
    assert ip._extract_sex("я съел овсянку") is None


def test_extract_body_part_recognizes_known_stems() -> None:
    assert ip._extract_body_part("замерь бицепс 35 см") == "bicep"
    assert ip._extract_body_part("обхват талии 80 см") == "waist"


def test_extract_body_part_returns_none_for_unknown_part() -> None:
    assert ip._extract_body_part("замерь что-то непонятное") is None


def test_infer_goal_type_detects_strength_keywords() -> None:
    from modules.fitness_tracker.domain import GoalType

    assert ip._infer_goal_type("поднять 100 кг в жиме") == GoalType.STRENGTH.value
    assert ip._infer_goal_type("накачать бицепс до 40 см") == GoalType.VOLUME.value
    assert ip._infer_goal_type("набрать 5 кг") == GoalType.WEIGHT.value


# --- parse() with a mocked matcher (fast, deterministic) --------------------


def test_parse_returns_none_category_when_matcher_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: False)

    result = ip.parse("я вешу 78")

    assert result.category is None


def test_parse_returns_none_category_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("weight", 0.3))

    result = ip.parse("что-то совсем нерелевантное")

    assert result.category is None


def test_parse_weight_extracts_the_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("weight", 0.9))

    result = ip.parse("я сегодня вешу 78 кг")

    assert result.category is ip.IntentCategory.WEIGHT
    assert result.entities == {"weight_kg": 78.0}
    assert result.missing_fields == []


def test_parse_weight_reports_missing_field_without_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("weight", 0.9))

    result = ip.parse("запиши мой вес")

    assert result.category is ip.IntentCategory.WEIGHT
    assert result.missing_fields == ["weight_kg"]


def test_parse_measurement_extracts_body_part_and_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("measurement", 0.9))

    result = ip.parse("замерь бицепс 35 см")

    assert result.entities == {"body_part": "bicep", "value_cm": 35.0}
    assert result.missing_fields == []


def test_parse_measurement_reports_missing_body_part(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("measurement", 0.9))

    result = ip.parse("замерь 35 см")

    assert "body_part" in result.missing_fields


def test_parse_meal_never_reports_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("meal", 0.9))

    result = ip.parse("я съел овсянку с бананом")

    assert result.missing_fields == []
    assert result.entities["description"] == "я съел овсянку с бананом"
    assert "grams" not in result.entities


def test_parse_meal_extracts_grams_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("meal", 0.9))

    result = ip.parse("поел курицу с рисом, было грамм 300")

    assert result.entities["grams"] == 300.0


def test_parse_goal_infers_type_and_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.fitness_tracker.domain import GoalType

    monkeypatch.setattr(ip, "_ensure_matcher_built", lambda: True)
    monkeypatch.setattr(ip._matcher, "best_match", lambda query: ("goal", 0.9))

    result = ip.parse("хочу поднять 100 кг в жиме до конца года")

    assert result.entities["goal_type"] == GoalType.STRENGTH.value
    assert result.entities["target_value"] == 100.0
    assert result.entities["unit"] == "kg"


def test_parse_empty_text_returns_none_category() -> None:
    assert ip.parse("").category is None


# --- parse() against the real embedding model (skipped if unavailable) -----


@pytest.fixture(scope="module", autouse=True)
def _ensure_real_matcher_built():
    if not ip._ensure_matcher_built():
        pytest.skip("Fitness intent parser's embedding model is unavailable in this environment")


@pytest.mark.parametrize(
    ("utterance", "expected_category"),
    [
        ("поменяй мой вес на 78", ip.IntentCategory.WEIGHT),
        ("я сегодня вешу 78 кг", ip.IntentCategory.WEIGHT),
        ("весы показали 78", ip.IntentCategory.WEIGHT),
        ("стал 78 кг", ip.IntentCategory.WEIGHT),
        ("мой рост 180 см", ip.IntentCategory.HEIGHT),
        ("мне 30 лет", ip.IntentCategory.AGE),
        ("я мужчина", ip.IntentCategory.SEX),
        ("замерь бицепс 35 см", ip.IntentCategory.MEASUREMENT),
        ("я съел овсянку с бананом", ip.IntentCategory.MEAL),
        ("сейчас поел курицу с рисом, было грамм 300", ip.IntentCategory.MEAL),
        ("на завтрак было яйцо и тост", ip.IntentCategory.MEAL),
        ("поставь цель набрать 5 кг до декабря", ip.IntentCategory.GOAL),
    ],
)
def test_parse_recognizes_real_utterances(utterance: str, expected_category: ip.IntentCategory) -> None:
    result = ip.parse(utterance)
    assert result.category is expected_category


def test_parse_off_topic_speech_returns_none_category() -> None:
    result = ip.parse("выключи компьютер")
    assert result.category is None
