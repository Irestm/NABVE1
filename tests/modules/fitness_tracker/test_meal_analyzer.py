from __future__ import annotations

import pytest

from modules.ai_bridge import vision
from modules.fitness_tracker import meal_analyzer


class _FakeAdapter:
    def __init__(self, name: str, reply: str | None = None, should_raise: bool = False) -> None:
        self.name = name
        self._reply = reply
        self._should_raise = should_raise

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        if self._should_raise:
            raise RuntimeError("adapter down")
        return self._reply or ""


_VALID_JSON_REPLY = (
    '{"description": "Овсянка с бананом", "estimated_calories": 350, '
    '"confidence": "medium", "macros": {"protein_g": 10, "fat_g": 5, "carbs_g": 60}}'
)


# --- estimate_from_photo -----------------------------------------------------


async def test_estimate_from_photo_raises_for_a_missing_file(tmp_path) -> None:
    with pytest.raises(meal_analyzer.MealAnalysisError):
        await meal_analyzer.estimate_from_photo(tmp_path / "does-not-exist.jpg")


async def test_estimate_from_photo_parses_a_valid_reply(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"fake-jpeg")

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        return _VALID_JSON_REPLY

    monkeypatch.setattr(meal_analyzer.vision, "analyze_image", fake_analyze_image)

    result = await meal_analyzer.estimate_from_photo(photo)

    assert result == {
        "description": "Овсянка с бананом",
        "estimated_calories": 350.0,
        "confidence": "medium",
        "macros": {"protein_g": 10.0, "fat_g": 5.0, "carbs_g": 60.0},
    }


async def test_estimate_from_photo_handles_a_markdown_fenced_reply(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"fake-jpeg")

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        return f"Вот результат:\n```json\n{_VALID_JSON_REPLY}\n```"

    monkeypatch.setattr(meal_analyzer.vision, "analyze_image", fake_analyze_image)

    result = await meal_analyzer.estimate_from_photo(photo)

    assert result["description"] == "Овсянка с бананом"


async def test_estimate_from_photo_raises_when_vision_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"fake-jpeg")

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        raise vision.VisionAnalysisError("no key")

    monkeypatch.setattr(meal_analyzer.vision, "analyze_image", fake_analyze_image)

    with pytest.raises(meal_analyzer.MealAnalysisError):
        await meal_analyzer.estimate_from_photo(photo)


async def test_estimate_from_photo_raises_on_unparseable_reply(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    photo = tmp_path / "meal.jpg"
    photo.write_bytes(b"fake-jpeg")

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        return "не могу помочь"

    monkeypatch.setattr(meal_analyzer.vision, "analyze_image", fake_analyze_image)

    with pytest.raises(meal_analyzer.MealAnalysisError):
        await meal_analyzer.estimate_from_photo(photo)


def test_normalize_confidence_falls_back_to_medium_for_invalid_values() -> None:
    assert meal_analyzer._normalize_confidence("very sure") == "medium"
    assert meal_analyzer._normalize_confidence("high") == "high"


def test_normalize_macros_ignores_non_numeric_and_unknown_fields() -> None:
    macros = meal_analyzer._normalize_macros({"protein_g": 10, "fat_g": "a lot", "unrelated": 5})
    assert macros == {"protein_g": 10.0}


# --- estimate_from_text -------------------------------------------------------


async def test_estimate_from_text_returns_the_first_adapters_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeAdapter("gemini_api", reply=_VALID_JSON_REPLY)
    monkeypatch.setattr(meal_analyzer, "candidate_chain", lambda text: [adapter])

    result = await meal_analyzer.estimate_from_text("овсянка с бананом")

    assert result["description"] == "Овсянка с бананом"
    assert result["estimated_calories"] == 350.0


async def test_estimate_from_text_falls_through_to_the_next_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = _FakeAdapter("a", should_raise=True)
    working = _FakeAdapter("b", reply=_VALID_JSON_REPLY)
    monkeypatch.setattr(meal_analyzer, "candidate_chain", lambda text: [failing, working])

    result = await meal_analyzer.estimate_from_text("овсянка с бананом")

    assert result["confidence"] == "medium"


async def test_estimate_from_text_raises_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meal_analyzer, "candidate_chain", lambda text: [_FakeAdapter("a", should_raise=True)])

    with pytest.raises(meal_analyzer.MealAnalysisError):
        await meal_analyzer.estimate_from_text("овсянка")


async def test_estimate_from_text_mentions_grams_in_the_prompt_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _CapturingAdapter(_FakeAdapter):
        async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
            captured["prompt"] = text
            return _VALID_JSON_REPLY

    monkeypatch.setattr(meal_analyzer, "candidate_chain", lambda text: [_CapturingAdapter("a")])

    await meal_analyzer.estimate_from_text("курица с рисом", grams=300)

    assert "300" in captured["prompt"]
