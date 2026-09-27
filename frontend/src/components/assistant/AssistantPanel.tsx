import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { ArrowDown, Bot, Check, Copy, PanelRightClose, RotateCcw, Send, Square, SquarePen } from "lucide-react";
import { ChatMarkdown } from "./ChatMarkdown";
import { useAssistantChat } from "./useAssistantChat";
import type { AssistantActions, AssistantContextProvider, ChatMessage } from "./types";

interface AssistantPanelProps {
  provider: AssistantContextProvider;
  onHide: () => void;
}

const MAX_INPUT_ROWS = 6;
const BOTTOM_SLACK_PX = 48;

function CopyButton({ text }: { text: string }): JSX.Element {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="asst-icon"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch((error: unknown) => console.error("Failed to copy assistant reply:", error));
      }}
      aria-label="Копировать ответ"
      title="Копировать"
    >
      {copied ? <Check size={15} /> : <Copy size={15} />}
    </button>
  );
}

function MessageItem({
  message,
  isLast,
  actions,
  provider,
  onRegenerate,
}: {
  message: ChatMessage;
  isLast: boolean;
  actions: AssistantActions;
  provider: AssistantContextProvider;
  onRegenerate: () => void;
}): JSX.Element {
  if (message.role === "user") {
    return (
      <li className="asst-msg asst-msg--user">
        <div className="asst-bubble asst-bubble--user">{message.content}</div>
      </li>
    );
  }
  const typing = message.pending && !message.content && !message.meta;
  return (
    <li className="asst-msg asst-msg--assistant">
      <span className="asst-avatar" aria-hidden="true">
        <Bot size={16} />
      </span>
      <div className="asst-msg__body">
        {provider.renderMeta?.(message, actions)}
        {typing ? (
          <div className="asst-typing" aria-label="Ассистент печатает">
            <span />
            <span />
            <span />
          </div>
        ) : (
          message.content && <ChatMarkdown text={message.content} />
        )}
        {message.error && <p className="asst-error">{message.error}</p>}
        {!message.pending && message.content && (
          <div className="asst-msg__actions">
            <CopyButton text={message.content} />
            {isLast && (
              <button
                type="button"
                className="asst-icon"
                onClick={onRegenerate}
                disabled={actions.busy}
                aria-label="Повторить ответ"
                title="Повторить"
              >
                <RotateCcw size={15} />
              </button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export function AssistantPanel({ provider, onHide }: AssistantPanelProps): JSX.Element {
  const chat = useAssistantChat(provider);
  const [draft, setDraft] = useState("");
  const [atBottom, setAtBottom] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const actions: AssistantActions = { send: chat.send, busy: chat.streaming };

  useEffect(() => {
    const node = listRef.current;
    if (atBottom && node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [chat.messages, atBottom]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) {
      return;
    }
    input.style.height = "auto";
    const lineHeight = Number.parseFloat(window.getComputedStyle(input).lineHeight) || 20;
    input.style.height = `${Math.min(input.scrollHeight, lineHeight * MAX_INPUT_ROWS + 16)}px`;
  }, [draft]);

  function submit(): void {
    if (!draft.trim() || chat.streaming) {
      return;
    }
    chat.send(draft);
    setDraft("");
    setAtBottom(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  const lastAssistant = chat.messages.map((message) => message.role).lastIndexOf("assistant");

  return (
    <section className="asst-panel" aria-label="Ассистент">
      <header className="asst-panel__head">
        <span className="asst-avatar" aria-hidden="true">
          <Bot size={16} />
        </span>
        <div className="asst-panel__title">
          <span>Ассистент</span>
          <span className="asst-panel__subtitle">{provider.title}</span>
        </div>
        <button type="button" className="asst-icon" onClick={chat.newChat} aria-label="Новый чат" title="Новый чат">
          <SquarePen size={17} />
        </button>
        <button type="button" className="asst-icon" onClick={onHide} aria-label="Скрыть панель" title="Скрыть панель">
          <PanelRightClose size={17} />
        </button>
      </header>

      <div
        className="asst-panel__log"
        ref={listRef}
        onScroll={(event) => {
          const node = event.currentTarget;
          setAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < BOTTOM_SLACK_PX);
        }}
      >
        {chat.loading ? (
          <p className="asst-muted">Загрузка…</p>
        ) : chat.messages.length === 0 ? (
          <div className="asst-empty">
            <p className="asst-muted">Спросите о словах, идиомах или о том, подойдёт ли вам сериал или фильм.</p>
            <div className="asst-chips">
              {provider.suggestions.map((suggestion) => (
                <button key={suggestion} type="button" className="asst-chip" onClick={() => chat.send(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="asst-list">
            {chat.messages.map((message, index) => (
              <MessageItem
                key={message.id}
                message={message}
                isLast={index === lastAssistant && index === chat.messages.length - 1}
                actions={actions}
                provider={provider}
                onRegenerate={chat.regenerate}
              />
            ))}
          </ul>
        )}
        {chat.error && <p className="asst-error">{chat.error}</p>}
      </div>

      {!atBottom && (
        <button
          type="button"
          className="asst-down"
          onClick={() => {
            setAtBottom(true);
            const node = listRef.current;
            if (node) {
              node.scrollTop = node.scrollHeight;
            }
          }}
          aria-label="Прокрутить вниз"
        >
          <ArrowDown size={16} /> Вниз
        </button>
      )}

      <form
        className="asst-input"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Спросите ассистента…"
          aria-label="Сообщение ассистенту"
        />
        {chat.streaming ? (
          <button type="button" className="asst-send asst-send--stop" onClick={chat.stop} aria-label="Остановить">
            <Square size={16} />
          </button>
        ) : (
          <button type="submit" className="asst-send" disabled={!draft.trim()} aria-label="Отправить">
            <Send size={16} />
          </button>
        )}
      </form>
    </section>
  );
}
