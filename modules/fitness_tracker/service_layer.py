from __future__ import annotations

from datetime import date, datetime

from core.logger import get_logger
from modules.fitness_tracker.calculations import calculate_bmi
from modules.fitness_tracker.domain import (
    BioProfileSnapshot,
    BodyMeasurement,
    Confidence,
    Goal,
    GoalType,
    MealLogEntry,
    MealSource,
    ProgressPhoto,
    Sex,
)
from modules.fitness_tracker.uow import FitnessUnitOfWork

logger = get_logger(__name__)


def get_current_bio_profile() -> BioProfileSnapshot | None:
    with FitnessUnitOfWork() as uow:
        return uow.bio_history.latest()


def list_weight_history() -> list[BioProfileSnapshot]:
    with FitnessUnitOfWork() as uow:
        return uow.bio_history.list_weight_history()


def _apply_bio_update(**changes: object) -> BioProfileSnapshot:
    """Appends one new row to fitness_bio_profile_history carrying every
    current field with `changes` overlaid on top, recalculating BMI whenever
    both height and weight are known. See modules.fitness_tracker's plan for
    why this is a single append-only log rather than a separate
    current-profile table plus a history table."""
    with FitnessUnitOfWork() as uow:
        previous = uow.bio_history.latest()
        sex: Sex | None = previous.sex if previous else None
        age: int | None = previous.age if previous else None
        height_cm: float | None = previous.height_cm if previous else None
        weight_kg: float | None = previous.weight_kg if previous else None

        sex = changes.get("sex", sex)  # type: ignore[assignment]
        age = changes.get("age", age)  # type: ignore[assignment]
        height_cm = changes.get("height_cm", height_cm)  # type: ignore[assignment]
        weight_kg = changes.get("weight_kg", weight_kg)  # type: ignore[assignment]

        bmi = calculate_bmi(weight_kg, height_cm) if height_cm and weight_kg else None
        snapshot = BioProfileSnapshot(sex=sex, age=age, height_cm=height_cm, weight_kg=weight_kg, bmi=bmi)
        uow.bio_history.add(snapshot)
        uow.commit()
        return snapshot


def update_weight(weight_kg: float) -> BioProfileSnapshot:
    return _apply_bio_update(weight_kg=weight_kg)


def update_height(height_cm: float) -> BioProfileSnapshot:
    return _apply_bio_update(height_cm=height_cm)


def update_age(age: int) -> BioProfileSnapshot:
    return _apply_bio_update(age=age)


def update_sex(sex: Sex) -> BioProfileSnapshot:
    return _apply_bio_update(sex=sex)


def update_bio_profile(
    *,
    sex: Sex | None = None,
    age: int | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
) -> BioProfileSnapshot:
    """Same underlying append-only update as update_weight/height/age/sex,
    but applies every given field as ONE history row — used by the REST
    profile form (core/main.py), which submits several fields from one
    save click, unlike a voice utterance, which only ever states one fact
    at a time and so calls the single-field functions above directly."""
    changes: dict[str, object] = {}
    if sex is not None:
        changes["sex"] = sex
    if age is not None:
        changes["age"] = age
    if height_cm is not None:
        changes["height_cm"] = height_cm
    if weight_kg is not None:
        changes["weight_kg"] = weight_kg
    return _apply_bio_update(**changes)


def add_measurement(body_part: str, value_cm: float) -> BodyMeasurement:
    with FitnessUnitOfWork() as uow:
        measurement = BodyMeasurement(body_part=body_part, value_cm=value_cm)
        measurement.id = uow.measurements.add(measurement)
        uow.commit()
        return measurement


def list_measurements(body_part: str | None = None) -> list[BodyMeasurement]:
    with FitnessUnitOfWork() as uow:
        return uow.measurements.list_all(body_part=body_part)


def add_goal(
    goal_type: GoalType,
    description: str,
    target_value: float | None = None,
    unit: str | None = None,
    deadline: date | None = None,
) -> Goal:
    with FitnessUnitOfWork() as uow:
        goal = Goal(goal_type=goal_type, description=description, target_value=target_value, unit=unit, deadline=deadline)
        goal.id = uow.goals.add(goal)
        uow.commit()
        return goal


def list_goals() -> list[Goal]:
    with FitnessUnitOfWork() as uow:
        return uow.goals.list_all()


def delete_goal(goal_id: int) -> bool:
    with FitnessUnitOfWork() as uow:
        deleted = uow.goals.delete(goal_id)
        uow.commit()
        return deleted


def achieve_goal(goal_id: int) -> Goal | None:
    with FitnessUnitOfWork() as uow:
        goal = uow.goals.get(goal_id)
        if goal is None:
            return None
        achieved_at = datetime.now()
        uow.goals.mark_achieved(goal_id, achieved_at)
        uow.commit()
        goal.achieved_at = achieved_at
        return goal


def log_meal(
    description: str,
    estimated_calories: float | None,
    confidence: Confidence,
    source: MealSource,
    protein_g: float | None = None,
    fat_g: float | None = None,
    carbs_g: float | None = None,
    photo_path: str | None = None,
) -> MealLogEntry:
    with FitnessUnitOfWork() as uow:
        entry = MealLogEntry(
            description=description,
            estimated_calories=estimated_calories,
            confidence=confidence,
            source=source,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            photo_path=photo_path,
        )
        entry.id = uow.meals.add(entry)
        uow.commit()
        return entry


def list_meals(limit: int | None = None) -> list[MealLogEntry]:
    with FitnessUnitOfWork() as uow:
        return uow.meals.list_all(limit=limit)


def delete_meal(meal_id: int) -> bool:
    with FitnessUnitOfWork() as uow:
        deleted = uow.meals.delete(meal_id)
        uow.commit()
        return deleted


def add_progress_photo(file_path: str, note: str | None = None) -> ProgressPhoto:
    with FitnessUnitOfWork() as uow:
        photo = ProgressPhoto(file_path=file_path, note=note)
        photo.id = uow.photos.add(photo)
        uow.commit()
        return photo


def list_progress_photos() -> list[ProgressPhoto]:
    with FitnessUnitOfWork() as uow:
        return uow.photos.list_all()


def delete_progress_photo(photo_id: int) -> bool:
    with FitnessUnitOfWork() as uow:
        deleted = uow.photos.delete(photo_id)
        uow.commit()
        return deleted
