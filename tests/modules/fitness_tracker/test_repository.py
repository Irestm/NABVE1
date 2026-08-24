from __future__ import annotations

from datetime import date

from modules.fitness_tracker.domain import (
    BioProfileSnapshot,
    BodyMeasurement,
    Goal,
    GoalType,
    MealLogEntry,
    ProgressPhoto,
)
from modules.fitness_tracker.uow import FitnessUnitOfWork


def test_bio_history_add_then_latest_round_trips(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.bio_history.add(BioProfileSnapshot(sex="male", age=30, height_cm=180.0, weight_kg=78.0, bmi=24.1))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        latest = uow.bio_history.latest()

    assert latest is not None
    assert latest.weight_kg == 78.0
    assert latest.bmi == 24.1


def test_bio_history_does_not_overwrite_previous_entries(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.bio_history.add(BioProfileSnapshot(sex="male", age=30, height_cm=180.0, weight_kg=78.0, bmi=24.1))
        uow.bio_history.add(BioProfileSnapshot(sex="male", age=30, height_cm=180.0, weight_kg=79.0, bmi=24.4))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        history = uow.bio_history.list_weight_history()
        latest = uow.bio_history.latest()

    assert [entry.weight_kg for entry in history] == [78.0, 79.0]
    assert latest is not None
    assert latest.weight_kg == 79.0


def test_bio_history_weight_history_excludes_entries_without_weight(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.bio_history.add(BioProfileSnapshot(sex="male", age=None, height_cm=None, weight_kg=None, bmi=None))
        uow.bio_history.add(BioProfileSnapshot(sex="male", age=30, height_cm=180.0, weight_kg=78.0, bmi=24.1))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        history = uow.bio_history.list_weight_history()

    assert len(history) == 1
    assert history[0].weight_kg == 78.0


def test_bio_history_latest_returns_none_when_empty(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.bio_history.latest() is None


def test_measurement_repository_add_list_and_filter(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.measurements.add(BodyMeasurement(body_part="bicep", value_cm=35.0))
        uow.measurements.add(BodyMeasurement(body_part="waist", value_cm=80.0))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        all_measurements = uow.measurements.list_all()
        bicep_only = uow.measurements.list_all(body_part="bicep")

    assert len(all_measurements) == 2
    assert len(bicep_only) == 1
    assert bicep_only[0].value_cm == 35.0


def test_goal_repository_add_list_and_delete(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        goal_id = uow.goals.add(
            Goal(goal_type=GoalType.WEIGHT, description="набрать 5 кг", target_value=83.0, unit="kg", deadline=date(2026, 12, 1))
        )
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        goals = uow.goals.list_all()
        assert len(goals) == 1
        assert goals[0].deadline == date(2026, 12, 1)
        deleted = uow.goals.delete(goal_id)
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert deleted is True
        assert uow.goals.list_all() == []


def test_goal_repository_mark_achieved(tmp_path) -> None:
    from datetime import datetime

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        goal_id = uow.goals.add(Goal(goal_type=GoalType.STRENGTH, description="жим 100 кг"))
        uow.commit()

    achieved_at = datetime(2026, 1, 1, 12, 0, 0)
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.goals.mark_achieved(goal_id, achieved_at)
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        goal = uow.goals.get(goal_id)

    assert goal is not None
    assert goal.achieved_at == achieved_at


def test_meal_log_repository_add_list_and_delete(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        meal_id = uow.meals.add(
            MealLogEntry(
                description="овсянка с бананом",
                estimated_calories=350.0,
                confidence="medium",
                source="text",
                protein_g=10.0,
                fat_g=5.0,
                carbs_g=60.0,
            )
        )
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        meals = uow.meals.list_all()
        assert len(meals) == 1
        assert meals[0].estimated_calories == 350.0
        deleted = uow.meals.delete(meal_id)
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert deleted is True
        assert uow.meals.list_all() == []


def test_meal_log_repository_list_all_respects_limit(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        for i in range(3):
            uow.meals.add(MealLogEntry(description=f"meal {i}", estimated_calories=100.0, confidence="low", source="manual"))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        limited = uow.meals.list_all(limit=2)

    assert len(limited) == 2


def test_progress_photo_repository_add_list_and_delete(tmp_path) -> None:
    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        photo_id = uow.photos.add(ProgressPhoto(file_path="/data/x.png", note="после месяца"))
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        photos = uow.photos.list_all()
        assert len(photos) == 1
        deleted = uow.photos.delete(photo_id)
        uow.commit()

    with FitnessUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert deleted is True
        assert uow.photos.list_all() == []
