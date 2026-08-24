import { useState } from "react";
import "./ApiKeyField.css";

interface ApiKeyFieldProps {
  label: string;
  configured: boolean;
  helperText?: string;
  configuredText?: string;
  notConfiguredText?: string;
  guideTitle?: string;
  guideSteps?: string[];
  onSave: (apiKey: string) => Promise<void>;
  onDelete: () => Promise<void>;
}

export function ApiKeyField({
  label,
  configured,
  helperText,
  configuredText = "Ключ активен.",
  notConfiguredText = "Ключ не задан.",
  guideTitle,
  guideSteps,
  onSave,
  onDelete,
}: ApiKeyFieldProps): JSX.Element {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [revealed, setRevealed] = useState(false);

  async function handleSave(): Promise<void> {
    const trimmed = input.trim();
    if (!trimmed) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSave(trimmed);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить ключ.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      await onDelete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить ключ.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="api-key-field">
      <span className="api-key-field__label">{label}</span>
      {helperText && <p className="status-detail">{helperText}</p>}
      <p className={configured ? "api-key-field__success" : "status-detail"}>
        {configured ? configuredText : notConfiguredText}
      </p>
      <div className="row">
        <input
          type={revealed ? "text" : "password"}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Вставьте свой API-ключ"
          disabled={busy}
        />
        <button
          type="button"
          className="api-key-field__eye"
          onClick={() => setRevealed((show) => !show)}
          disabled={busy}
          aria-label={revealed ? "Скрыть ключ" : "Показать ключ"}
          title={revealed ? "Скрыть ключ" : "Показать ключ"}
        >
          {revealed ? "🙈" : "👁"}
        </button>
        <button type="button" onClick={() => void handleSave()} disabled={busy || !input.trim()}>
          {busy ? "…" : "Сохранить"}
        </button>
        {configured && (
          <button type="button" onClick={() => void handleDelete()} disabled={busy}>
            Удалить
          </button>
        )}
      </div>
      {error && <p className="status-error">{error}</p>}
      {guideTitle && guideSteps && guideSteps.length > 0 && (
        <>
          <button
            type="button"
            className="api-key-field__toggle"
            onClick={() => setGuideOpen((open) => !open)}
          >
            {guideOpen ? "Скрыть инструкцию" : guideTitle}
          </button>
          {guideOpen && (
            <ol className="api-key-field__steps">
              {guideSteps.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
