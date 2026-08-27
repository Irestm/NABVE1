import { Dumbbell, MessageCircle, Plug, Terminal } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import type { CollapsibleCardAccent } from "./CollapsibleCard";
import { SettingsPanel } from "./SettingsPanel";
import type { DesignId } from "../design/types";
import "./Sidebar.css";

export type Page = "assistant" | "commands" | "fitness" | "integrations";

const ACCENT_VARS: Record<CollapsibleCardAccent, string> = {
  blue: "var(--accent-blue)",
  purple: "var(--accent-purple)",
  amber: "var(--accent-amber)",
  green: "var(--accent-green)",
  red: "var(--accent-red)",
  cyan: "var(--glow-listening)",
};

interface SidebarItem {
  id: Page;
  label: string;
  icon: ReactNode;
  accent: CollapsibleCardAccent;
}

// Every item gets its own color (see the 2026-08-24 follow-up redesign) —
// same accent palette CollapsibleCard.tsx already uses for the "Ассистент"
// page's cards, so the whole app draws from one consistent set of hues
// instead of inventing a second palette just for the sidebar.
const ITEMS: SidebarItem[] = [
  { id: "assistant", label: "Ассистент", icon: <MessageCircle size={26} />, accent: "blue" },
  { id: "commands", label: "Системные команды", icon: <Terminal size={26} />, accent: "purple" },
  { id: "fitness", label: "Фитнес", icon: <Dumbbell size={26} />, accent: "green" },
  { id: "integrations", label: "Интеграции", icon: <Plug size={26} />, accent: "red" },
];

interface SidebarProps {
  activePage: Page;
  onSelect: (page: Page) => void;
  designId: DesignId;
  onDesignChange: (id: DesignId) => void;
}

// Replaces the old horizontal .app-tabs strip (see the 2026-08-24 redesign)
// — a vertical column reads better on both a narrow phone (more vertical
// space than horizontal, unlike a 5-6-item row that had to scroll) and a
// wide Electron window. "Настройки ассистента" is pinned at the bottom,
// separate from the page items above it — it opens a modal, not a page.
export function Sidebar({ activePage, onSelect, designId, onDesignChange }: SidebarProps): JSX.Element {
  return (
    <nav className="sidebar" aria-label="Разделы NABVE">
      <div className="sidebar__items">
        {ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar__item${activePage === item.id ? " sidebar__item--active" : ""}`}
            style={{ "--item-accent": ACCENT_VARS[item.accent] } as CSSProperties}
            onClick={() => onSelect(item.id)}
            aria-current={activePage === item.id}
          >
            <span className="sidebar__item-icon" aria-hidden="true">
              {item.icon}
            </span>
            <span className="sidebar__item-label">{item.label}</span>
          </button>
        ))}
      </div>

      <div className="sidebar__footer">
        <SettingsPanel designId={designId} onDesignChange={onDesignChange} />
      </div>
    </nav>
  );
}
