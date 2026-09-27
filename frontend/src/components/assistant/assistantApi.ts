import { requestJson, requestStream } from "../../api/client";
import type { ChatMessage } from "./types";
import { normalizeState } from "./panelState";
import type { PanelState, PanelStore } from "./panelState";

export interface Thread {
  id: number;
  module: string;
  scope: string;
  scope_id: number;
  created_at: string;
}

export function listThreads(apiBase: string, module: string, scope: string, scopeId: number): Promise<Thread[]> {
  const query = new URLSearchParams({ module, scope, scope_id: String(scopeId) });
  return requestJson<Thread[]>(`${apiBase}/assistant/threads?${query.toString()}`);
}

export function createThread(apiBase: string, module: string, scope: string, scopeId: number): Promise<Thread> {
  return requestJson<Thread>(`${apiBase}/assistant/threads`, {
    method: "POST",
    body: JSON.stringify({ module, scope, scope_id: scopeId }),
  });
}

export function listMessages(apiBase: string, threadId: number): Promise<ChatMessage[]> {
  return requestJson<ChatMessage[]>(`${apiBase}/assistant/threads/${threadId}/messages`);
}

export function streamMessage(
  apiBase: string,
  threadId: number,
  body: Record<string, unknown>,
  signal: AbortSignal,
): Promise<Response> {
  return requestStream(`${apiBase}/assistant/threads/${threadId}/messages`, body, signal);
}

export function uiSettingsStore(apiBase: string, key: string): PanelStore {
  return {
    async load(): Promise<PanelState> {
      const response = await requestJson<{ key: string; value: unknown }>(`${apiBase}/ui-settings/${key}`);
      return normalizeState(response.value);
    },
    async save(state: PanelState): Promise<void> {
      await requestJson(`${apiBase}/ui-settings/${key}`, { method: "PUT", body: JSON.stringify({ value: state }) });
    },
  };
}
