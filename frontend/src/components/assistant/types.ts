import type { ReactNode } from "react";

export interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  meta: Record<string, unknown> | null;
  pending?: boolean;
  error?: string;
}

export interface SendOptions {
  action?: Record<string, unknown>;
}

export interface AssistantActions {
  send: (text: string, options?: SendOptions) => void;
  busy: boolean;
}

export interface AssistantContextProvider {
  module: string;
  apiBase: string;
  scope: string;
  scopeId: number;
  title: string;
  suggestions: string[];
  getContext: () => Record<string, unknown>;
  renderMeta?: (message: ChatMessage, actions: AssistantActions) => ReactNode;
}
