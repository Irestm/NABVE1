import { useEffect, useState } from "react";
import { getAIBridgeStatus, runCommand } from "../api/client";
import type { AIBridgeStatus, ProviderName } from "../types";
import "./StatusPanel.css";

const PROVIDER_LABELS: Record<ProviderName, string> = {
  gemini: "Gemini",
  chatgpt: "ChatGPT",
  deepseek: "DeepSeek",
  grok: "Grok",
};

export function StatusPanel(): JSX.Element {
  const [status, setStatus] = useState<AIBridgeStatus | null>(null);
  const [revealing, setRevealing] = useState(false);

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
    try {
      await runCommand("ai_bridge_show_provider");
    } finally {
      setRevealing(false);
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

      <div className="status-panel__providers">
        {(status?.order ?? (["gemini", "chatgpt", "deepseek", "grok"] as ProviderName[])).map((name) => {
          const isActive = status?.active_provider === name;
          const limited = status?.limit_reached?.[name];
          return (
            <div
              key={name}
              className={`status-panel__provider${isActive ? " status-panel__provider--active" : ""}${
                limited ? " status-panel__provider--limited" : ""
              }`}
            >
              <span className="status-panel__provider-dot" />
              <span className="status-panel__provider-name">{PROVIDER_LABELS[name]}</span>
              {limited && <span className="status-panel__provider-badge">лимит</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
