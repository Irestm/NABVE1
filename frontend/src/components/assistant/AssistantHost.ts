import { createContext, useContext } from "react";

export interface AssistantHostValue {
  open: boolean;
  toggle: () => void;
}

export const AssistantHostContext = createContext<AssistantHostValue | null>(null);

export function useAssistantHost(): AssistantHostValue | null {
  return useContext(AssistantHostContext);
}
