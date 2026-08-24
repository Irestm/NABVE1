import { useState } from "react";
import { runCommand } from "../api/client";
import { useOneShotVoiceInput } from "../hooks/useOneShotVoiceInput";
import "./CodeAnalysisPanel.css";

type Source = "code" | "github" | "screen";

export function CodeAnalysisPanel(): JSX.Element {
  const [source, setSource] = useState<Source>("code");
  const [code, setCode] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [instruction, setInstruction] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const voiceInput = useOneShotVoiceInput((transcribed) => {
    setInstruction((current) => (current.trim() ? `${current.trim()} ${transcribed}` : transcribed));
  });

  const ready =
    instruction.trim().length > 0 &&
    (source === "screen" || (source === "code" ? code.trim().length > 0 : githubUrl.trim().length > 0));

  async function handleAnalyze(): Promise<void> {
    if (!ready) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response =
        source === "code"
          ? await runCommand("analyze_code", { code: code.trim(), instruction: instruction.trim() })
          : source === "github"
            ? await runCommand("analyze_github_file", {
                url: githubUrl.trim(),
                instruction: instruction.trim(),
              })
            : await runCommand("analyze_active_editor", { instruction: instruction.trim() });
      setResult(typeof response.result?.analysis === "string" ? response.result.analysis : response.message);
    } catch (err) {
      console.error("Failed to analyze code:", err);
      setError(err instanceof Error ? err.message : "Не удалось проанализировать код.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="code-analysis-panel">
      <div className="row">
        <button
          type="button"
          className={`api-key-field__toggle${source === "code" ? " code-analysis-panel__source--active" : ""}`}
          onClick={() => setSource("code")}
        >
          Вставить код
        </button>
        <button
          type="button"
          className={`api-key-field__toggle${source === "github" ? " code-analysis-panel__source--active" : ""}`}
          onClick={() => setSource("github")}
        >
          Ссылка на GitHub
        </button>
        <button
          type="button"
          className={`api-key-field__toggle${source === "screen" ? " code-analysis-panel__source--active" : ""}`}
          onClick={() => setSource("screen")}
        >
          Текущий экран
        </button>
      </div>

      {source === "code" && (
        <textarea
          className="text-editing-panel__textarea"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="Вставьте код сюда"
          rows={8}
        />
      )}
      {source === "github" && (
        <input
          type="text"
          value={githubUrl}
          onChange={(event) => setGithubUrl(event.target.value)}
          placeholder="https://github.com/владелец/репозиторий/blob/ветка/путь/к/файлу"
        />
      )}
      {source === "screen" && (
        <p className="status-detail">
          Проанализирует то, что сейчас видно на экране (в PyCharm — точное содержимое открытого файла, в
          остальных редакторах — по скриншоту через Gemini; нужен настроенный Gemini-ключ в Интеграциях).
        </p>
      )}

      <div className="row">
        <input
          type="text"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Что сделать с кодом? (объясни, найди баг, ...)"
        />
        <button
          type="button"
          className="api-key-field__eye"
          onClick={voiceInput.start}
          disabled={voiceInput.recording}
          aria-label="Надиктовать задачу"
          title="Надиктовать задачу"
        >
          {voiceInput.recording ? "🔴" : "🎤"}
        </button>
        <button type="button" onClick={() => void handleAnalyze()} disabled={busy || !ready}>
          {busy ? "…" : "Анализировать"}
        </button>
      </div>
      {voiceInput.error && <p className="status-error">{voiceInput.error}</p>}
      {error && <p className="status-error">{error}</p>}
      {result && (
        <div className="text-editing-panel__result">
          <p className="settings-panel__label">Результат</p>
          <textarea className="text-editing-panel__textarea" value={result} readOnly rows={8} />
        </div>
      )}
    </div>
  );
}
