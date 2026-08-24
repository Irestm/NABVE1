import { useEffect, useState } from "react";
import { confirmCommand, listPendingMessages, runCommand, speak } from "../api/client";
import type { PendingMessage } from "../types";
import "./MessagingPanel.css";

// Same "just refetch, nothing else propagates a live update" reasoning as
// ImageGenerationPanel.tsx — a message can arrive from any of up to 3
// Telegram accounts at any time, with no push channel to the frontend.
const POLL_INTERVAL_MS = 8000;

export function MessagingPanel(): JSX.Element {
  const [messages, setMessages] = useState<PendingMessage[]>([]);
  const [error, setError] = useState("");
  const [replyDrafts, setReplyDrafts] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  async function refresh(): Promise<void> {
    try {
      setMessages(await listPendingMessages());
      setError("");
    } catch (err) {
      console.error("Failed to load pending messages:", err);
      setError("Не удалось загрузить сообщения.");
    }
  }

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  async function handleReadAloud(message: PendingMessage): Promise<void> {
    try {
      const spoken = await speak(message.text, "ru");
      if (spoken.audio_wav_base64) {
        const audio = new Audio(`data:audio/wav;base64,${spoken.audio_wav_base64}`);
        void audio.play();
      }
    } catch (err) {
      console.error("Failed to read the message aloud:", err);
      setError("Не удалось прочитать вслух.");
    }
  }

  async function handleReply(message: PendingMessage): Promise<void> {
    const text = (replyDrafts[message.id] ?? "").trim();
    if (!text) {
      return;
    }
    setBusyId(message.id);
    setError("");
    try {
      const response = await runCommand("messaging_reply", {
        message_id: message.id,
        text,
        expected_received_at: message.received_at,
      });
      if (response.status === "confirmation_required" && response.token) {
        await confirmCommand(response.token, true);
      }
      setMessages((current) => current.filter((m) => m.id !== message.id));
      setReplyDrafts((current) => {
        const next = { ...current };
        delete next[message.id];
        return next;
      });
    } catch (err) {
      console.error("Failed to send the reply:", err);
      setError(err instanceof Error ? err.message : "Не удалось отправить ответ.");
    } finally {
      setBusyId(null);
    }
  }

  if (messages.length === 0 && !error) {
    return <></>;
  }

  return (
    <div className="section messaging-panel">
      <h3>Сообщения</h3>
      {error && <p className="status-error">{error}</p>}
      {messages.map((message) => (
        <div key={message.id} className="messaging-panel__card">
          <p className="messaging-panel__from">Пришло сообщение от {message.sender_label} — прочитать вслух?</p>
          <p className="messaging-panel__text">{message.text}</p>
          <div className="row">
            <button type="button" onClick={() => void handleReadAloud(message)}>
              Прочитать вслух
            </button>
          </div>
          <div className="row">
            <input
              type="text"
              value={replyDrafts[message.id] ?? ""}
              onChange={(event) =>
                setReplyDrafts((current) => ({ ...current, [message.id]: event.target.value }))
              }
              placeholder="Ответить..."
            />
            <button
              type="button"
              onClick={() => void handleReply(message)}
              disabled={busyId === message.id || !(replyDrafts[message.id] ?? "").trim()}
            >
              {busyId === message.id ? "…" : "Отправить"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
