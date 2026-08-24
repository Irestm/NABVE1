import { CheckCircle2, Dumbbell, Ruler, Scale, Trash2, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { addFitnessGoal, deleteFitnessGoal, listFitnessGoals } from "../api/client";
import type { FitnessGoal, FitnessGoalType } from "../types";
import "./FitnessGoalsSection.css";

const GOAL_TYPE_LABELS: Record<FitnessGoalType, string> = {
  weight: "Вес",
  strength: "Сила",
  volume: "Объём",
};

const GOAL_TYPE_ICONS: Record<FitnessGoalType, LucideIcon> = {
  weight: Scale,
  strength: Dumbbell,
  volume: Ruler,
};

export function FitnessGoalsSection(): JSX.Element {
  const [goals, setGoals] = useState<FitnessGoal[]>([]);
  const [error, setError] = useState("");
  const [description, setDescription] = useState("");
  const [goalType, setGoalType] = useState<FitnessGoalType>("weight");
  const [targetValue, setTargetValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function refresh(): Promise<void> {
    try {
      setGoals(await listFitnessGoals());
      setError("");
    } catch (err) {
      console.error("Failed to load goals:", err);
      setError("Не удалось загрузить цели.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleAdd(): Promise<void> {
    if (!description.trim()) {
      return;
    }
    setSaving(true);
    try {
      await addFitnessGoal(goalType, description.trim(), targetValue.trim() ? Number(targetValue) : null);
      setDescription("");
      setTargetValue("");
      await refresh();
    } catch (err) {
      console.error("Failed to add a goal:", err);
      setError("Не удалось сохранить цель.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(goalId: number): Promise<void> {
    setDeletingId(goalId);
    try {
      await deleteFitnessGoal(goalId);
      setGoals((current) => current.filter((goal) => goal.id !== goalId));
    } catch (err) {
      console.error("Failed to delete a goal:", err);
      setError("Не удалось удалить цель.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="fitness-goals">
      {error && <p className="status-error">{error}</p>}

      <div className="row">
        <select value={goalType} onChange={(event) => setGoalType(event.target.value as FitnessGoalType)}>
          <option value="weight">Вес</option>
          <option value="strength">Сила</option>
          <option value="volume">Объём</option>
        </select>
        <input
          type="text"
          placeholder="Описание цели"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <div className="row">
        <input
          type="number"
          placeholder="Целевое значение (необязательно)"
          value={targetValue}
          onChange={(event) => setTargetValue(event.target.value)}
        />
        <button type="button" onClick={() => void handleAdd()} disabled={saving || !description.trim()}>
          {saving ? "…" : "Добавить"}
        </button>
      </div>

      <div className="fitness-goals__grid">
        {goals.map((goal) => {
          const Icon = GOAL_TYPE_ICONS[goal.goal_type];
          return (
            <div
              key={goal.id}
              className={`fitness-goals__card${goal.achieved_at ? " fitness-goals__card--achieved" : ""}`}
            >
              <span className="fitness-goals__icon">
                <Icon size={20} />
              </span>
              <div className="fitness-goals__body">
                <p className="fitness-goals__description">{goal.description}</p>
                <div className="fitness-goals__chips">
                  <span className="fitness-goals__chip">{GOAL_TYPE_LABELS[goal.goal_type]}</span>
                  {goal.target_value != null && (
                    <span className="fitness-goals__chip">
                      цель: {goal.target_value}
                      {goal.unit ? ` ${goal.unit}` : ""}
                    </span>
                  )}
                  {goal.achieved_at && (
                    <span className="fitness-goals__chip fitness-goals__chip--achieved">
                      <CheckCircle2 size={12} /> достигнута
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                className="fitness-goals__delete"
                onClick={() => void handleDelete(goal.id)}
                disabled={deletingId === goal.id}
                title="Удалить цель"
              >
                <Trash2 size={16} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
