from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from core.voice import module_context
from modules.fitness_tracker import fitness_chat
from modules.fitness_tracker import meal_analyzer as fitness_meal_analyzer
from modules.fitness_tracker import progress_photos as fitness_progress_photos
from modules.fitness_tracker import service_layer as fitness_service_layer
from modules.fitness_tracker.uow import FitnessUnitOfWork

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "state.db"

    def factory() -> FitnessUnitOfWork:
        return FitnessUnitOfWork(db_path=db_path)

    monkeypatch.setattr(fitness_service_layer, "FitnessUnitOfWork", factory)
    monkeypatch.setattr(fitness_progress_photos, "FITNESS_MEDIA_DIR", tmp_path / "fitness_media")
    yield
    module_context.deactivate()


def test_fitness_endpoints_without_auth_are_rejected() -> None:
    response = client.get("/api/fitness/profile")
    assert response.status_code == 401


def test_get_profile_is_none_initially() -> None:
    response = client.get("/api/fitness/profile", headers=AUTH)

    assert response.status_code == 200
    assert response.json() is None


def test_update_profile_computes_bmi_and_category() -> None:
    response = client.post(
        "/api/fitness/profile", headers=AUTH, json={"sex": "male", "age": 30, "height_cm": 180.0, "weight_kg": 78.0}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bmi"] == pytest.approx(24.07, abs=0.01)
    assert body["bmi_category"] == "норма"


def test_weight_history_reflects_updates() -> None:
    client.post("/api/fitness/profile", headers=AUTH, json={"weight_kg": 78.0})
    client.post("/api/fitness/profile", headers=AUTH, json={"weight_kg": 79.0})

    response = client.get("/api/fitness/weight_history", headers=AUTH)

    assert [e["weight_kg"] for e in response.json()] == [78.0, 79.0]


def test_add_and_list_measurements() -> None:
    add_response = client.post("/api/fitness/measurements", headers=AUTH, json={"body_part": "bicep", "value_cm": 35.0})
    assert add_response.status_code == 200

    list_response = client.get("/api/fitness/measurements", headers=AUTH)
    assert len(list_response.json()) == 1

    filtered_response = client.get("/api/fitness/measurements", headers=AUTH, params={"body_part": "waist"})
    assert filtered_response.json() == []


def test_add_list_and_delete_goal() -> None:
    add_response = client.post(
        "/api/fitness/goals", headers=AUTH, json={"goal_type": "weight", "description": "набрать 5 кг", "target_value": 83.0}
    )
    assert add_response.status_code == 200
    goal_id = add_response.json()["id"]

    list_response = client.get("/api/fitness/goals", headers=AUTH)
    assert len(list_response.json()) == 1

    delete_response = client.delete(f"/api/fitness/goals/{goal_id}", headers=AUTH)
    assert delete_response.status_code == 200
    assert client.get("/api/fitness/goals", headers=AUTH).json() == []


def test_add_goal_rejects_an_unknown_goal_type() -> None:
    response = client.post("/api/fitness/goals", headers=AUTH, json={"goal_type": "not_a_type", "description": "x"})
    assert response.status_code == 400


def test_delete_goal_404s_for_unknown_id() -> None:
    response = client.delete("/api/fitness/goals/999", headers=AUTH)
    assert response.status_code == 404


async def test_log_meal_text_uses_the_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_estimate_from_text(description: str, grams: float | None = None) -> dict:
        return {"description": description, "estimated_calories": 350.0, "confidence": "medium", "macros": {"protein_g": 10.0}}

    monkeypatch.setattr(fitness_meal_analyzer, "estimate_from_text", fake_estimate_from_text)

    response = client.post("/api/fitness/meals/text", headers=AUTH, json={"description": "овсянка с бананом"})

    assert response.status_code == 200
    body = response.json()
    assert body["estimated_calories"] == 350.0
    assert body["protein_g"] == 10.0
    assert body["has_photo"] is False


async def test_log_meal_text_still_logs_when_analysis_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_estimate_from_text(description: str, grams: float | None = None) -> dict:
        raise fitness_meal_analyzer.MealAnalysisError("нет ключа")

    monkeypatch.setattr(fitness_meal_analyzer, "estimate_from_text", fake_estimate_from_text)

    response = client.post("/api/fitness/meals/text", headers=AUTH, json={"description": "овсянка"})

    assert response.status_code == 200
    assert response.json()["estimated_calories"] is None


def test_list_and_delete_meals() -> None:
    fitness_service_layer.log_meal("курица", 400.0, "high", "manual")

    list_response = client.get("/api/fitness/meals", headers=AUTH)
    assert len(list_response.json()) == 1
    meal_id = list_response.json()[0]["id"]

    delete_response = client.delete(f"/api/fitness/meals/{meal_id}", headers=AUTH)
    assert delete_response.status_code == 200
    assert client.get("/api/fitness/meals", headers=AUTH).json() == []


def test_delete_meal_404s_for_unknown_id() -> None:
    assert client.delete("/api/fitness/meals/999", headers=AUTH).status_code == 404


async def test_log_meal_photo_saves_the_file_and_returns_the_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_estimate_from_photo(image_path) -> dict:
        assert image_path.is_file()
        return {"description": "Салат", "estimated_calories": 200.0, "confidence": "low", "macros": {}}

    monkeypatch.setattr(fitness_meal_analyzer, "estimate_from_photo", fake_estimate_from_photo)

    response = client.post(
        "/api/fitness/meals/photo", headers=AUTH, files={"photo": ("meal.jpg", b"fake-jpeg", "image/jpeg")}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Салат"
    assert body["has_photo"] is True

    photo_response = client.get(f"/api/fitness/meals/{body['id']}/photo", headers=AUTH)
    assert photo_response.status_code == 200
    assert photo_response.content == b"fake-jpeg"


def test_get_meal_photo_404s_for_a_meal_without_a_photo() -> None:
    fitness_service_layer.log_meal("курица", 400.0, "high", "manual")
    meal_id = client.get("/api/fitness/meals", headers=AUTH).json()[0]["id"]

    response = client.get(f"/api/fitness/meals/{meal_id}/photo", headers=AUTH)

    assert response.status_code == 404


def test_add_list_get_and_delete_progress_photo() -> None:
    add_response = client.post(
        "/api/fitness/progress_photos",
        headers=AUTH,
        data={"note": "после месяца"},
        files={"photo": ("progress.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )
    assert add_response.status_code == 200
    photo_id = add_response.json()["id"]
    assert add_response.json()["note"] == "после месяца"

    list_response = client.get("/api/fitness/progress_photos", headers=AUTH)
    assert len(list_response.json()) == 1

    file_response = client.get(f"/api/fitness/progress_photos/{photo_id}/file", headers=AUTH)
    assert file_response.content == b"fake-jpeg-bytes"

    delete_response = client.delete(f"/api/fitness/progress_photos/{photo_id}", headers=AUTH)
    assert delete_response.status_code == 200
    assert client.get("/api/fitness/progress_photos", headers=AUTH).json() == []


def test_delete_progress_photo_404s_for_unknown_id() -> None:
    assert client.delete("/api/fitness/progress_photos/999", headers=AUTH).status_code == 404


async def test_fitness_chat_returns_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_answer_question(text: str, language: str = "ru") -> str:
        return f"Ответ на: {text}"

    monkeypatch.setattr(fitness_chat, "answer_question", fake_answer_question)

    response = client.post("/api/fitness/chat", headers=AUTH, json={"text": "сколько мне нужно белка"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Ответ на: сколько мне нужно белка"


async def test_fitness_chat_returns_503_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_answer_question(text: str, language: str = "ru") -> str:
        raise fitness_chat.FitnessChatError("недоступно")

    monkeypatch.setattr(fitness_chat, "answer_question", fake_answer_question)

    response = client.post("/api/fitness/chat", headers=AUTH, json={"text": "вопрос"})

    assert response.status_code == 503


def test_status_reflects_the_active_module_context() -> None:
    module_context.activate("fitness")

    response = client.get("/api/status", headers=AUTH)

    assert response.json()["active_module_context"] == "fitness"
