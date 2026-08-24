import { useEffect, useRef, useState } from "react";
import { sendFitnessChatMessage } from "../api/client";
import "./FitnessChatWidget.css";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export function FitnessChatWidget(): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleSend(): Promise<void> {
    const text = input.trim();
    if (!text || sending) {
      return;
    }
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);
    setError("");
    try {
      const reply = await sendFitnessChatMessage(text);
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
    } catch (err) {
      console.error("Failed to send a fitness chat message:", err);
      setError("Не удалось получить ответ.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fitness-chat-widget">
      {error && <p className="status-error">{error}</p>}

      <div className="fitness-chat-widget__log" ref={logRef}>
        {messages.length === 0 ? (
          <p className="status-detail">Спросите о питании, тренировках или своих показателях.</p>
        ) : (
          messages.map((message, index) => (
            <p key={index} className={`fitness-chat-widget__message fitness-chat-widget__message--${message.role}`}>
              {message.text}
            </p>
          ))
        )}
      </div>

      <div className="row">
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Вопрос о питании, тренировках или показателях"
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              void handleSend();
            }
          }}
        />
        <button type="button" onClick={() => void handleSend()} disabled={sending || !input.trim()}>
          {sending ? "…" : "Отправить"}
        </button>
      </div>
    </div>
  );
}
