import { useEffect, useRef, useState } from "react";
import { confirmCommand, sendTextQuery } from "../api/client";
import "./TextChat.css";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

interface PendingConfirmation {
  token: string;
}

export function TextChat(): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
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

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleSend(): Promise<void> {
    const text = input.trim();
    if (!text || sending || pending) {
      return;
    }
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);
    setError("");
    try {
      const response = await sendTextQuery(text);
      setMessages((prev) => [...prev, { role: "assistant", text: response.reply_text }]);
      setPending(response.status === "confirmation_required" && response.token ? { token: response.token } : null);
    } catch (error) {
      console.error("Failed to send a text query:", error);
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
      const response = await confirmCommand(pending.token, approved);
      setMessages((prev) => [...prev, { role: "assistant", text: response.message }]);
    } catch (error) {
      console.error("Failed to confirm a pending command:", error);
      setError("Не удалось подтвердить действие.");
    } finally {
      setPending(null);
      setSending(false);
    }
  }

  return (
    <div className="text-chat">
      {error && <p className="status-error">{error}</p>}

      <div className="text-chat__log" ref={logRef}>
        {messages.length === 0 ? (
          <p className="status-detail">Напишите команду или вопрос — ответ придёт текстом, без голоса.</p>
        ) : (
          messages.map((message, index) => (
            <p key={index} className={`text-chat__message text-chat__message--${message.role}`}>
              {message.text}
            </p>
          ))
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
