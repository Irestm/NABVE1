from __future__ import annotations

import pytest

from modules.fitness_tracker import service_layer
from modules.fitness_tracker.domain import GoalType
from modules.fitness_tracker.uow import FitnessUnitOfWork


@pytest.fixture(autouse=True)
def _fitness_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "state.db"

    def factory() -> FitnessUnitOfWork:
        return FitnessUnitOfWork(db_path=db_path)

    monkeypatch.setattr(service_layer, "FitnessUnitOfWork", factory)
    yield db_path


def test_get_current_bio_profile_is_none_initially() -> None:
    assert service_layer.get_current_bio_profile() is None


def test_update_weight_creates_a_profile_snapshot() -> None:
    snapshot = service_layer.update_weight(78.0)

    assert snapshot.weight_kg == 78.0
    assert service_layer.get_current_bio_profile().weight_kg == 78.0


def test_update_height_then_weight_computes_bmi() -> None:
    service_layer.update_height(180.0)
    snapshot = service_layer.update_weight(78.0)

    assert snapshot.bmi == pytest.approx(24.07, abs=0.01)


def test_updates_preserve_previously_set_fields() -> None:
    service_layer.update_sex("female")
    service_layer.update_age(28)
    snapshot = service_layer.update_weight(60.0)

    assert snapshot.sex == "female"
    assert snapshot.age == 28
    assert snapshot.weight_kg == 60.0


def test_update_bio_profile_applies_multiple_fields_in_one_row() -> None:
    snapshot = service_layer.update_bio_profile(sex="female", age=28, height_cm=165.0, weight_kg=60.0)

    assert snapshot.sex == "female"
    assert snapshot.age == 28
    assert snapshot.bmi == pytest.approx(22.04, abs=0.01)
    assert len(service_layer.list_weight_history()) == 1


def test_update_bio_profile_with_no_fields_still_appends_a_snapshot_of_current_state() -> None:
    service_layer.update_weight(70.0)

    snapshot = service_layer.update_bio_profile()

    assert snapshot.weight_kg == 70.0


def test_list_weight_history_returns_entries_in_order() -> None:
    service_layer.update_weight(78.0)
    service_layer.update_weight(79.0)

    history = service_layer.list_weight_history()
    assert [entry.weight_kg for entry in history] == [78.0, 79.0]


def test_add_measurement_and_list_by_body_part() -> None:
    service_layer.add_measurement("bicep", 35.0)
    service_layer.add_measurement("waist", 80.0)

    assert len(service_layer.list_measurements()) == 2
    assert len(service_layer.list_measurements(body_part="bicep")) == 1


def test_add_goal_list_and_delete() -> None:
    goal = service_layer.add_goal(GoalType.WEIGHT, "набрать 5 кг", target_value=83.0, unit="kg")

    assert len(service_layer.list_goals()) == 1
    assert service_layer.delete_goal(goal.id) is True
    assert service_layer.list_goals() == []


def test_achieve_goal_sets_achieved_at() -> None:
    goal = service_layer.add_goal(GoalType.STRENGTH, "жим 100 кг")

    achieved = service_layer.achieve_goal(goal.id)

    assert achieved is not None
    assert achieved.achieved_at is not None


def test_achieve_goal_returns_none_for_unknown_id() -> None:
    assert service_layer.achieve_goal(999) is None


def test_log_meal_and_list() -> None:
    service_layer.log_meal("овсянка с бананом", 350.0, "medium", "text")

    meals = service_layer.list_meals()
    assert len(meals) == 1
    assert meals[0].description == "овсянка с бананом"


def test_delete_meal() -> None:
    entry = service_layer.log_meal("курица с рисом", 500.0, "high", "manual")

    assert service_layer.delete_meal(entry.id) is True
    assert service_layer.list_meals() == []


def test_add_and_list_and_delete_progress_photo() -> None:
    photo = service_layer.add_progress_photo("/data/x.png", note="после месяца")

    assert len(service_layer.list_progress_photos()) == 1
    assert service_layer.delete_progress_photo(photo.id) is True
    assert service_layer.list_progress_photos() == []
