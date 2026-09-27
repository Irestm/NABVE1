import { PanelRightOpen, Sparkles } from "lucide-react";
import { useAssistantHost } from "./AssistantHost";

interface AssistantToggleButtonProps {
  className?: string;
}

export function AssistantToggleButton({ className }: AssistantToggleButtonProps): JSX.Element | null {
  const host = useAssistantHost();
  if (!host) {
    return null;
  }
  const label = host.open ? "Скрыть ассистента" : "Спросить ассистента об этом разделе";
  return (
    <button
      type="button"
      className={`${className ?? "ql-icon-button"} asst-toggle${host.open ? " asst-toggle--active" : ""}`}
      onClick={host.toggle}
      aria-label={label}
      aria-pressed={host.open}
      title={label}
    >
      {host.open ? <PanelRightOpen size={20} /> : <Sparkles size={20} />}
    </button>
  );
}
