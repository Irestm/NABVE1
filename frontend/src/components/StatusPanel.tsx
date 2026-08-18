import { useEffect, useState } from "react";
import { getAIBridgeStatus, runCommand } from "../api/client";
import type { AIBridgeStatus, ProviderName } from "../types";
import { ProviderCard } from "./ProviderCard";
import "./StatusPanel.css";

const ALL_PROVIDERS: ProviderName[] = ["gemini", "chatgpt", "deepseek", "grok"];

export function StatusPanel(): JSX.Element {
  const [status, setStatus] = useState<AIBridgeStatus | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [busyProvider, setBusyProvider] = useState<ProviderName | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function poll(): Promise<void> {
      try {
        const next = await getAIBridgeStatus();
        if (!cancelled) {
          setStatus(next);
        }
      } catch {
        // Backend not reachable yet; leave last known status displayed.
      }
    }

    void poll();
    const interval = window.setInterval(() => void poll(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  async function handleReveal(): Promise<void> {
    setRevealing(true);
    setError("");
    try {
      await runCommand("ai_bridge_show_provider");
    } catch (err) {
      console.error("Failed to reveal the active AI provider's window:", err);
      setError("Не удалось показать окно провайдера.");
    } finally {
      setRevealing(false);
    }
  }

  async function handleLogin(provider: ProviderName): Promise<void> {
    setBusyProvider(provider);
    setError("");
    try {
      await runCommand("ai_bridge_provider_login", { provider });
    } catch (err) {
      console.error(`Failed to open the login window for ${provider}:`, err);
      setError("Не удалось открыть окно входа.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleLogout(provider: ProviderName): Promise<void> {
    setBusyProvider(provider);
    setError("");
    try {
      await runCommand("ai_bridge_provider_logout", { provider });
      // Logging out resets the local session immediately — no need to wait
      // for the next 5s poll to reflect it.
      setStatus((prev) => (prev ? { ...prev, logged_in: { ...prev.logged_in, [provider]: false } } : prev));
    } catch (err) {
      console.error(`Failed to log out of ${provider}:`, err);
      setError("Не удалось выйти из провайдера.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleImportSession(provider: ProviderName): Promise<void> {
    setBusyProvider(provider);
    setError("");
    try {
      const response = await runCommand("ai_bridge_provider_import_session", { provider });
      if (response.status === "failed") {
        setError(response.message || "Не удалось импортировать сессию.");
        return;
      }
      // The next 5s poll will confirm it, but reflect success immediately
      // rather than leaving the card on "Гость" for up to 5s.
      setStatus((prev) => (prev ? { ...prev, logged_in: { ...prev.logged_in, [provider]: true } } : prev));
    } catch (err) {
      console.error(`Failed to import a browser session for ${provider}:`, err);
      setError("Не удалось импортировать сессию.");
    } finally {
      setBusyProvider(null);
    }
  }

  return (
    <div className="status-panel">
      <div className="status-panel__row status-panel__row--header">
        <span className="status-panel__label">ИИ-провайдер</span>
        <button
          className="status-panel__reveal"
          onClick={() => void handleReveal()}
          disabled={revealing}
          title="Показать вкладку провайдера"
        >
          {revealing ? "…" : "показать"}
        </button>
      </div>

      {error && <p className="status-error">{error}</p>}

      <div className="status-panel__provider-grid">
        {(status?.order ?? ALL_PROVIDERS).map((name) => (
          <ProviderCard
            key={name}
            provider={name}
            active={status?.active_provider === name}
            limited={Boolean(status?.limit_reached?.[name])}
            loggedIn={Boolean(status?.logged_in?.[name])}
            busy={busyProvider === name}
            onLogin={() => void handleLogin(name)}
            onLogout={() => void handleLogout(name)}
            onImportSession={() => void handleImportSession(name)}
          />
        ))}
      </div>
    </div>
  );
}
