import { useCallback, useEffect, useRef, useState } from "react";
import { createThread, listMessages, listThreads, streamMessage } from "./assistantApi";
import { readEvents } from "./sse";
import type { AssistantContextProvider, ChatMessage, SendOptions } from "./types";

export interface AssistantChat {
  messages: ChatMessage[];
  streaming: boolean;
  loading: boolean;
  error: string;
  send: (text: string, options?: SendOptions) => void;
  stop: () => void;
  regenerate: () => void;
  newChat: () => void;
}

let localIds = 0;

function localId(): string {
  localIds += 1;
  return `local-${localIds}`;
}

export function useAssistantChat(provider: AssistantContextProvider): AssistantChat {
  const { apiBase, module, scope, scopeId } = provider;
  const [threadId, setThreadId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const providerRef = useRef(provider);
  providerRef.current = provider;

  useEffect(() => {
    let cancelled = false;
    abortRef.current?.abort();
    setLoading(true);
    setMessages([]);
    setThreadId(null);
    setError("");
    listThreads(apiBase, module, scope, scopeId)
      .then(async (threads) => {
        const latest = threads[0];
        if (!latest) {
          return;
        }
        const loaded = await listMessages(apiBase, latest.id);
        if (!cancelled) {
          setThreadId(latest.id);
          setMessages(loaded);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить чат.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, module, scope, scopeId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const ensureThread = useCallback(async (): Promise<number> => {
    if (threadId !== null) {
      return threadId;
    }
    const thread = await createThread(apiBase, module, scope, scopeId);
    setThreadId(thread.id);
    return thread.id;
  }, [apiBase, module, scope, scopeId, threadId]);

  const run = useCallback(
    async (body: Record<string, unknown>, userText: string | null): Promise<void> => {
      if (abortRef.current) {
        return;
      }
      const controller = new AbortController();
      abortRef.current = controller;
      const replyId = localId();
      setError("");
      setStreaming(true);
      setMessages((previous) => [
        ...previous,
        ...(userText ? [{ id: localId(), role: "user" as const, content: userText, meta: null }] : []),
        { id: replyId, role: "assistant", content: "", meta: null, pending: true },
      ]);
      const patch = (update: (message: ChatMessage) => ChatMessage): void =>
        setMessages((previous) => previous.map((message) => (message.id === replyId ? update(message) : message)));
      try {
        const id = await ensureThread();
        const response = await streamMessage(
          apiBase,
          id,
          { ...body, context: providerRef.current.getContext() },
          controller.signal,
        );
        for await (const event of readEvents(response.body as ReadableStream<Uint8Array>)) {
          if (event.event === "delta") {
            const text = String(event.data.text ?? "");
            patch((message) => ({ ...message, content: message.content + text }));
          } else if (event.event === "difficulty" || event.event === "offer") {
            patch((message) => ({ ...message, meta: { ...(message.meta ?? {}), [event.event]: event.data } }));
          } else if (event.event === "error") {
            patch((message) => ({ ...message, error: String(event.data.message ?? "Ошибка ассистента") }));
          } else if (event.event === "done" && typeof event.data.message_id === "number") {
            const serverId = event.data.message_id;
            patch((message) => ({ ...message, id: serverId }));
          }
        }
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          patch((message) => ({ ...message, error: err instanceof Error ? err.message : "Нет ответа." }));
        }
      } finally {
        setMessages((previous) =>
          previous
            .map((message) => (message.pending ? { ...message, pending: false } : message))
            .filter((message) => message.role === "user" || message.content || message.meta || message.error),
        );
        abortRef.current = null;
        setStreaming(false);
      }
    },
    [apiBase, ensureThread],
  );

  const send = useCallback(
    (text: string, options?: SendOptions): void => {
      const content = text.trim();
      if (!content && !options?.action) {
        return;
      }
      void run({ content, ...(options?.action ? { action: options.action } : {}) }, content || null);
    },
    [run],
  );

  const stop = useCallback((): void => {
    abortRef.current?.abort();
  }, []);

  const regenerate = useCallback((): void => {
    setMessages((previous) => {
      const lastUser = previous.map((message) => message.role).lastIndexOf("user");
      return previous.filter((message, index) => message.role === "user" || index < lastUser);
    });
    void run({ regenerate: true }, null);
  }, [run]);

  const newChat = useCallback((): void => {
    abortRef.current?.abort();
    createThread(apiBase, module, scope, scopeId)
      .then((thread) => {
        setThreadId(thread.id);
        setMessages([]);
        setError("");
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось начать новый чат."));
  }, [apiBase, module, scope, scopeId]);

  return { messages, streaming, loading, error, send, stop, regenerate, newChat };
}
