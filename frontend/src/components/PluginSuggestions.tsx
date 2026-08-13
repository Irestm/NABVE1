import { useEffect, useState } from "react";
import {
  approvePluginSuggestion,
  getPluginSuggestionCode,
  listPluginSuggestions,
  rejectPluginSuggestion,
} from "../api/client";
import type { PluginSuggestion } from "../types";

const POLL_INTERVAL_MS = 15000;

export function PluginSuggestions(): JSX.Element | null {
  const [suggestions, setSuggestions] = useState<PluginSuggestion[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [codeById, setCodeById] = useState<Record<number, string>>({});
  const [viewedIds, setViewedIds] = useState<Set<number>>(new Set());
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    let hasSucceededOnce = false;
    let startupAttempt = 0;
    // The regular setInterval below already makes this self-healing, but
    // at POLL_INTERVAL_MS=15000 that means up to 15s of a visible error
    // banner after every launch — this effect fires the moment the
    // renderer's JS executes, which can beat the backend's ~1-2s
    // uvicorn+plugin startup (see core.watchdog.supervisor) to the punch.
    // Retry fast (bounded) until the first success, same fix as App.tsx's
    // own /api/status poll already gets away with via its short 1.5s
    // interval; once real data has loaded once, fall back to the normal
    // interval below for ongoing refresh.
    const STARTUP_MAX_ATTEMPTS = 5;
    const STARTUP_RETRY_DELAY_MS = 1000;

    async function poll(): Promise<void> {
      try {
        const result = await listPluginSuggestions();
        if (!cancelled) {
          setSuggestions(result);
          setError("");
          hasSucceededOnce = true;
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (!hasSucceededOnce && startupAttempt < STARTUP_MAX_ATTEMPTS) {
          startupAttempt += 1;
          setTimeout(() => void poll(), STARTUP_RETRY_DELAY_MS);
          return;
        }
        console.error("Failed to poll plugin suggestions:", error);
        setError("Не удалось получить предложения плагинов");
      }
    }

    void poll();
    const interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  async function handleShowCode(suggestion: PluginSuggestion): Promise<void> {
    if (expandedId === suggestion.id) {
      setExpandedId(null);
      return;
    }
    setViewedIds((prev) => new Set(prev).add(suggestion.id));
    if (!codeById[suggestion.id]) {
      try {
        const code = await getPluginSuggestionCode(suggestion.id);
        setCodeById((prev) => ({ ...prev, [suggestion.id]: code }));
      } catch (error) {
        console.error("Failed to load plugin suggestion code:", error);
        setError("Не удалось загрузить код плагина");
        return;
      }
    }
    setExpandedId(suggestion.id);
  }

  async function handleApprove(suggestion: PluginSuggestion): Promise<void> {
    setBusyId(suggestion.id);
    try {
      await approvePluginSuggestion(suggestion.id);
      setSuggestions((prev) => prev.filter((item) => item.id !== suggestion.id));
    } catch (error) {
      console.error("Failed to approve a plugin suggestion:", error);
      setError("Не удалось включить плагин");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(suggestion: PluginSuggestion): Promise<void> {
    setBusyId(suggestion.id);
    try {
      await rejectPluginSuggestion(suggestion.id);
      setSuggestions((prev) => prev.filter((item) => item.id !== suggestion.id));
    } catch (error) {
      console.error("Failed to reject a plugin suggestion:", error);
      setError("Не удалось отклонить плагин");
    } finally {
      setBusyId(null);
    }
  }

  if (suggestions.length === 0 && !error) {
    return null;
  }

  return (
    <div className="plugin-suggestions">
      <h3>Предложенные плагины</h3>
      {error && <p className="status-error">{error}</p>}
      {suggestions.map((suggestion) => {
        const canQuickApprove = !suggestion.requires_manual_review || viewedIds.has(suggestion.id);
        const isBusy = busyId === suggestion.id;
        return (
          <div key={suggestion.id} className="plugin-suggestion-card">
            <p className="plugin-suggestion-message">{suggestion.message}</p>

            {suggestion.requires_manual_review && (
              <div className="plugin-suggestion-warning">
                Требует ручного просмотра кода перед включением
                <ul>
                  {suggestion.safety_flags.map((flag) => (
                    <li key={flag}>{flag}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="row">
              <button onClick={() => void handleShowCode(suggestion)}>
                {expandedId === suggestion.id ? "Скрыть код" : "Показать код"}
              </button>
              <button
                disabled={!canQuickApprove || isBusy}
                title={
                  canQuickApprove
                    ? undefined
                    : "Сначала откройте код, чтобы включить этот плагин"
                }
                onClick={() => void handleApprove(suggestion)}
              >
                Включить
              </button>
              <button className="danger" disabled={isBusy} onClick={() => void handleReject(suggestion)}>
                Отклонить
              </button>
            </div>

            {expandedId === suggestion.id && (
              <pre className="plugin-suggestion-code">{codeById[suggestion.id] ?? "Загрузка..."}</pre>
            )}
          </div>
        );
      })}
    </div>
  );
}
