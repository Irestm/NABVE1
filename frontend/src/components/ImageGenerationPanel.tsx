import { useEffect, useRef, useState } from "react";
import { deleteGeneratedImage, getGeneratedImageFileUrl, listGeneratedImages } from "../api/client";
import type { GeneratedImage } from "../types";
import "./ImageGenerationPanel.css";

// A generated image only ever reaches the frontend by refetching the list —
// voice/text-typed commands (core/voice/pipeline.py's dispatch, reached via
// sendTextQuery) only ever return spoken reply_text, no structured result
// the way the manual command-button panel's runCommand() does — so a plain
// interval is the only channel that works uniformly regardless of how the
// generation was triggered (voice, typed, or the command panel), without
// threading a new field through the shared voice-response models just for
// this one command.
const POLL_INTERVAL_MS = 5000;

export function ImageGenerationPanel(): JSX.Element {
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const knownIds = useRef<Set<number> | null>(null);

  async function refresh(): Promise<void> {
    try {
      const fetched = await listGeneratedImages();
      if (knownIds.current !== null) {
        const previous = knownIds.current;
        setNewIds(new Set(fetched.filter((image) => !previous.has(image.id)).map((image) => image.id)));
      }
      knownIds.current = new Set(fetched.map((image) => image.id));
      setImages(fetched);
      setError("");
    } catch (err) {
      console.error("Failed to load generated images:", err);
      setError("Не удалось загрузить сгенерированные изображения.");
    }
  }

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  async function handleDelete(imageId: number): Promise<void> {
    setDeletingId(imageId);
    try {
      await deleteGeneratedImage(imageId);
      setImages((current) => current.filter((image) => image.id !== imageId));
    } catch (err) {
      console.error("Failed to delete generated image:", err);
      setError("Не удалось удалить изображение.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="image-generation-panel">
      <div className="image-generation-panel__header">
        {images.length === 0 && !error ? (
          <p className="status-detail">Пока ничего не сгенерировано.</p>
        ) : (
          <span />
        )}
        <button type="button" className="api-key-field__toggle" onClick={() => void refresh()}>
          Обновить
        </button>
      </div>
      {error && <p className="status-error">{error}</p>}
      <div className="image-generation-panel__grid">
        {images.map((image) => (
          <div
            key={image.id}
            className={`image-generation-panel__card${newIds.has(image.id) ? " image-generation-panel__card--new" : ""}`}
          >
            <a href={getGeneratedImageFileUrl(image.id)} target="_blank" rel="noreferrer">
              <img
                className="image-generation-panel__thumb"
                src={getGeneratedImageFileUrl(image.id)}
                alt={image.prompt}
              />
            </a>
            <p className="image-generation-panel__prompt" title={image.prompt}>
              {image.prompt}
            </p>
            <div className="row">
              <a
                className="image-generation-panel__download"
                href={getGeneratedImageFileUrl(image.id)}
                download={`nabve-${image.id}.png`}
              >
                Скачать
              </a>
              <button
                type="button"
                onClick={() => void handleDelete(image.id)}
                disabled={deletingId === image.id}
              >
                {deletingId === image.id ? "…" : "Удалить"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
