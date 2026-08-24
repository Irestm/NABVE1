import { useState } from "react";
import { runCommand } from "../api/client";
import { useOneShotVoiceInput } from "../hooks/useOneShotVoiceInput";
import "./TextEditingPanel.css";

export function TextEditingPanel(): JSX.Element {
  const [text, setText] = useState("");
  const [instruction, setInstruction] = useState("");
  const [edited, setEdited] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const voiceInput = useOneShotVoiceInput((transcribed) => {
    setInstruction((current) => (current.trim() ? `${current.trim()} ${transcribed}` : transcribed));
  });

  async function handleApply(): Promise<void> {
    const trimmedText = text.trim();
    const trimmedInstruction = instruction.trim();
    if (!trimmedText || !trimmedInstruction) {
      return;
    }
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const response = await runCommand("edit_text", { text: trimmedText, instruction: trimmedInstruction });
      setEdited(typeof response.result?.edited_text === "string" ? response.result.edited_text : response.message);
    } catch (err) {
      console.error("Failed to edit text:", err);
      setError(err instanceof Error ? err.message : "Не удалось отредактировать текст.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(edited);
      setCopied(true);
    } catch (err) {
      console.error("Failed to copy the edited text:", err);
    }
  }

  function handleReplace(): void {
    setText(edited);
    setEdited("");
  }

  return (
    <div className="text-editing-panel">
      <p className="status-detail">
        Вставьте текст, опишите, что с ним сделать («сделай короче», «исправь грамматику», «переведи на
        английский») — и нажмите «Применить».
      </p>
      <textarea
        className="text-editing-panel__textarea"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Вставьте текст сюда"
        rows={6}
      />
      <div className="row">
        <input
          type="text"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Что сделать с текстом?"
        />
        <button
          type="button"
          className="api-key-field__eye"
          onClick={voiceInput.start}
          disabled={voiceInput.recording}
          aria-label="Надиктовать инструкцию"
          title="Надиктовать инструкцию"
        >
          {voiceInput.recording ? "🔴" : "🎤"}
        </button>
        <button
          type="button"
          onClick={() => void handleApply()}
          disabled={busy || !text.trim() || !instruction.trim()}
        >
          {busy ? "…" : "Применить"}
        </button>
      </div>
      {voiceInput.error && <p className="status-error">{voiceInput.error}</p>}
      {error && <p className="status-error">{error}</p>}
      {edited && (
        <div className="text-editing-panel__result">
          <p className="settings-panel__label">Результат</p>
          <textarea className="text-editing-panel__textarea" value={edited} readOnly rows={6} />
          <div className="row">
            <button type="button" onClick={() => void handleCopy()}>
              {copied ? "Скопировано" : "Скопировать"}
            </button>
            <button type="button" onClick={handleReplace}>
              Заменить исходный текст
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
