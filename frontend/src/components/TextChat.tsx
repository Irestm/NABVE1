import { useEffect, useRef, useState } from "react";
import { confirmCommand, getConversation, sendTextQuery } from "../api/client";
import type { ConversationTurn } from "../types";
import "./TextChat.css";

interface PendingConfirmation {
  token: string;
}

const REFRESH_INTERVAL_MS = 2000;

function startOfDay(iso: string): number {
  const date = new Date(iso);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function dayLabel(iso: string): string {
  const today = startOfDay(new Date().toISOString());
  const turnDay = startOfDay(iso);
  const dayMs = 24 * 60 * 60 * 1000;
  if (turnDay === today) {
    return "Сегодня";
  }
  if (turnDay === today - dayMs) {
    return "Вчера";
  }
  return new Date(iso).toLocaleDateString();
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function TextChat(): JSX.Element {
  // The backend records every turn — spoken and typed — into
  // modules/conversation_log, so this panel doubles as a running,
  // restart-surviving transcript of the voice conversation, not just an
  // echo of what was typed here. serverTurns is that log; optimistic holds
  // a just-typed message for the moment before the next refresh confirms
  // it (a spoken/AI reply can take a few seconds to come back).
  const [serverTurns, setServerTurns] = useState<ConversationTurn[]>([]);
  const [optimistic, setOptimistic] = useState<ConversationTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // Set when a reply comes back with status "confirmation_required" (e.g.
  // "выключи компьютер"). Regression this fixes: without this, the next
  // typed message ("да") went through the exact same interpret/AI pipeline
  // as any other message — "да" alone matches no rule and isn't a real
  // question, so it just got answered as a fresh, unrelated chat message
  // instead of ever confirming the pending dangerous command.
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);

  async function refresh(): Promise<void> {
    try {
      const turns = await getConversation();
      setServerTurns(turns);
      setOptimistic([]);
    } catch (err) {
      console.error("Failed to load the conversation log:", err);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!busyRef.current) {
        void refresh();
      }
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    busyRef.current = sending || pending !== null;
  }, [sending, pending]);

  const turns = [...serverTurns, ...optimistic];

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [serverTurns, optimistic]);

  async function handleSend(): Promise<void> {
    const text = input.trim();
    if (!text || sending || pending) {
      return;
    }
    setOptimistic([{ timestamp: new Date().toISOString(), role: "user", text, source: "text" }]);
    setInput("");
    setSending(true);
    setError("");
    try {
      const response = await sendTextQuery(text);
      setPending(response.status === "confirmation_required" && response.token ? { token: response.token } : null);
      await refresh();
    } catch (err) {
      console.error("Failed to send a text query:", err);
      setError("Не удалось отправить сообщение.");
    } finally {
      setSending(false);
    }
  }

  async function handleConfirm(approved: boolean): Promise<void> {
    if (!pending) {
      return;
    }
    setSending(true);
    setError("");
    try {
      await confirmCommand(pending.token, approved);
    } catch (err) {
      console.error("Failed to confirm a pending command:", err);
      setError("Не удалось подтвердить действие.");
    } finally {
      setPending(null);
      setSending(false);
      await refresh();
    }
  }

  return (
    <div className="text-chat">
      {error && <p className="status-error">{error}</p>}

      <div className="text-chat__log" ref={logRef}>
        {turns.length === 0 ? (
          <p className="status-detail">Напишите команду или вопрос — ответ придёт текстом. Здесь же видно, что ассистент отвечал голосом.</p>
        ) : (
          turns.map((turn, index) => {
            const previous = turns[index - 1];
            const showDay = !previous || startOfDay(previous.timestamp) !== startOfDay(turn.timestamp);
            return (
              <div className="text-chat__turn" key={`${turn.timestamp}-${index}`}>
                {showDay && <p className="text-chat__day">{dayLabel(turn.timestamp)}</p>}
                <p className={`text-chat__message text-chat__message--${turn.role}`}>
                  <span className="text-chat__text">{turn.text}</span>
                  <span className="text-chat__time">{timeLabel(turn.timestamp)}</span>
                </p>
              </div>
            );
          })
        )}
      </div>

      {pending ? (
        <div className="row">
          <button className="danger" disabled={sending} onClick={() => void handleConfirm(true)}>
            Подтвердить
          </button>
          <button disabled={sending} onClick={() => void handleConfirm(false)}>
            Отмена
          </button>
        </div>
      ) : (
        <div className="row">
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Например: открой стим"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleSend();
              }
            }}
          />
          <button onClick={() => void handleSend()} disabled={sending || !input.trim()}>
            {sending ? "…" : "Отправить"}
          </button>
        </div>
      )}
    </div>
  );
}
