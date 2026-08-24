import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  addFitnessProgressPhoto,
  deleteFitnessProgressPhoto,
  getFitnessProgressPhotoFileUrl,
  listFitnessProgressPhotos,
} from "../api/client";
import type { FitnessProgressPhoto } from "../types";
import "./FitnessProgressPhotoGallery.css";

// Purely local UI preference, same "small per-viewer convenience" shape as
// App.tsx's own DESIGN_STORAGE_KEY/VoiceRecorder's voice-language key — the
// user decides per-browser whether this (sensitive, body-image-related)
// section is even shown, per the task spec's explicit privacy note.
const HIDE_STORAGE_KEY = "fitnessHideProgressPhotos";

function readHidden(): boolean {
  try {
    return window.localStorage.getItem(HIDE_STORAGE_KEY) === "1";
  } catch (error) {
    console.error("Failed to read the progress-photo visibility preference:", error);
    return false;
  }
}

export function FitnessProgressPhotoGallery(): JSX.Element {
  const [hidden, setHidden] = useState(readHidden);
  const [photos, setPhotos] = useState<FitnessProgressPhoto[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh(): Promise<void> {
    try {
      setPhotos(await listFitnessProgressPhotos());
      setError("");
    } catch (err) {
      console.error("Failed to load progress photos:", err);
      setError("Не удалось загрузить прогресс-фото.");
    }
  }

  useEffect(() => {
    if (!hidden) {
      void refresh();
    }
  }, [hidden]);

  function toggleHidden(): void {
    const next = !hidden;
    setHidden(next);
    try {
      window.localStorage.setItem(HIDE_STORAGE_KEY, next ? "1" : "0");
    } catch (err) {
      console.error("Failed to persist the progress-photo visibility preference:", err);
    }
  }

  async function handlePhotoSelected(file: File | undefined): Promise<void> {
    if (!file) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await addFitnessProgressPhoto(file, note.trim() || undefined);
      setNote("");
      await refresh();
    } catch (err) {
      console.error("Failed to upload a progress photo:", err);
      setError("Не удалось сохранить фото.");
    } finally {
      setSaving(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  async function handleDelete(photoId: number): Promise<void> {
    setDeletingId(photoId);
    try {
      await deleteFitnessProgressPhoto(photoId);
      setPhotos((current) => current.filter((photo) => photo.id !== photoId));
    } catch (err) {
      console.error("Failed to delete a progress photo:", err);
      setError("Не удалось удалить фото.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="fitness-progress-photos">
      <div className="fitness-progress-photos__toolbar">
        <label className="fitness-progress-photos__hide-toggle">
          <input type="checkbox" checked={hidden} onChange={toggleHidden} />
          Скрыть эту секцию
        </label>
      </div>

      {hidden ? (
        <p className="status-detail">Секция скрыта в настройках этого браузера.</p>
      ) : (
        <>
          {error && <p className="status-error">{error}</p>}
          <div className="row">
            <input type="text" placeholder="Заметка (необязательно)" value={note} onChange={(event) => setNote(event.target.value)} />
            <label className="fitness-progress-photos__upload-button">
              Добавить фото
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={(event) => void handlePhotoSelected(event.target.files?.[0])}
                disabled={saving}
              />
            </label>
          </div>

          <div className="fitness-progress-photos__grid">
            {photos.map((photo) => (
              <div key={photo.id} className="fitness-progress-photos__card">
                <div className="fitness-progress-photos__thumb-wrap">
                  <img
                    className="fitness-progress-photos__thumb"
                    src={getFitnessProgressPhotoFileUrl(photo.id)}
                    alt={photo.note ?? "Прогресс-фото"}
                  />
                  <button
                    type="button"
                    className="fitness-progress-photos__delete"
                    onClick={() => void handleDelete(photo.id)}
                    disabled={deletingId === photo.id}
                    title="Удалить фото"
                  >
                    <Trash2 size={14} />
                  </button>
                  <span className="fitness-progress-photos__date">
                    {new Date(photo.taken_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}
                  </span>
                </div>
                {photo.note && <p className="fitness-progress-photos__note">{photo.note}</p>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
