import { Beef, Droplet, Flame, Trash2, Wheat } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  deleteFitnessMeal,
  getFitnessMealPhotoUrl,
  listFitnessMeals,
  logFitnessMealPhoto,
  logFitnessMealText,
} from "../api/client";
import type { FitnessMeal } from "../types";
import "./FitnessMealDiary.css";

const CONFIDENCE_LABELS: Record<string, string> = { high: "высокая", medium: "средняя", low: "низкая" };

export function FitnessMealDiary(): JSX.Element {
  const [meals, setMeals] = useState<FitnessMeal[]>([]);
  const [error, setError] = useState("");
  const [description, setDescription] = useState("");
  const [grams, setGrams] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh(): Promise<void> {
    try {
      setMeals(await listFitnessMeals(20));
      setError("");
    } catch (err) {
      console.error("Failed to load meals:", err);
      setError("Не удалось загрузить дневник питания.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleAddText(): Promise<void> {
    if (!description.trim()) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await logFitnessMealText(description.trim(), grams.trim() ? Number(grams) : null);
      setDescription("");
      setGrams("");
      await refresh();
    } catch (err) {
      console.error("Failed to log a meal:", err);
      setError("Не удалось оценить и записать приём пищи.");
    } finally {
      setSaving(false);
    }
  }

  async function handlePhotoSelected(file: File | undefined): Promise<void> {
    if (!file) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await logFitnessMealPhoto(file);
      await refresh();
    } catch (err) {
      console.error("Failed to log a meal photo:", err);
      setError("Не удалось проанализировать фото еды.");
    } finally {
      setSaving(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  async function handleDelete(mealId: number): Promise<void> {
    setDeletingId(mealId);
    try {
      await deleteFitnessMeal(mealId);
      setMeals((current) => current.filter((meal) => meal.id !== mealId));
    } catch (err) {
      console.error("Failed to delete a meal:", err);
      setError("Не удалось удалить запись.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="fitness-meal-diary">
      {error && <p className="status-error">{error}</p>}

      <div className="row">
        <input
          type="text"
          placeholder="Что съели?"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <input
          type="number"
          placeholder="грамм (необязательно)"
          value={grams}
          onChange={(event) => setGrams(event.target.value)}
        />
      </div>
      <div className="row">
        <button type="button" onClick={() => void handleAddText()} disabled={saving || !description.trim()}>
          {saving ? "…" : "Записать"}
        </button>
        <label className="fitness-meal-diary__photo-button">
          Добавить по фото
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={(event) => void handlePhotoSelected(event.target.files?.[0])}
            disabled={saving}
          />
        </label>
      </div>

      <div className="fitness-meal-diary__grid">
        {meals.map((meal) => (
          <div key={meal.id} className="fitness-meal-diary__card">
            {meal.has_photo ? (
              <img className="fitness-meal-diary__thumb" src={getFitnessMealPhotoUrl(meal.id)} alt={meal.description} />
            ) : (
              <span className="fitness-meal-diary__thumb fitness-meal-diary__thumb--placeholder">
                <Flame size={20} />
              </span>
            )}
            <div className="fitness-meal-diary__info">
              <div className="fitness-meal-diary__top-row">
                <p className="fitness-meal-diary__description">{meal.description}</p>
                {meal.estimated_calories != null && (
                  <span className="fitness-meal-diary__calories">
                    <Flame size={12} />
                    {meal.estimated_calories.toFixed(0)} ккал
                  </span>
                )}
              </div>
              <div className="fitness-meal-diary__macros">
                {meal.protein_g != null && (
                  <span className="fitness-meal-diary__macro fitness-meal-diary__macro--protein">
                    <Beef size={12} /> {meal.protein_g.toFixed(0)} г
                  </span>
                )}
                {meal.carbs_g != null && (
                  <span className="fitness-meal-diary__macro fitness-meal-diary__macro--carbs">
                    <Wheat size={12} /> {meal.carbs_g.toFixed(0)} г
                  </span>
                )}
                {meal.fat_g != null && (
                  <span className="fitness-meal-diary__macro fitness-meal-diary__macro--fat">
                    <Droplet size={12} /> {meal.fat_g.toFixed(0)} г
                  </span>
                )}
                <span className="fitness-meal-diary__meta">оценка: {CONFIDENCE_LABELS[meal.confidence] ?? meal.confidence}</span>
              </div>
            </div>
            <button
              type="button"
              className="fitness-meal-diary__delete"
              onClick={() => void handleDelete(meal.id)}
              disabled={deletingId === meal.id}
              title="Удалить запись"
            >
              <Trash2 size={16} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
