import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import "./CollapsibleCard.css";

export type CollapsibleCardAccent = "purple" | "blue" | "amber" | "green" | "red" | "cyan";

const ACCENT_VARS: Record<CollapsibleCardAccent, string> = {
  purple: "var(--accent-purple)",
  blue: "var(--accent-blue)",
  amber: "var(--accent-amber)",
  green: "var(--accent-green)",
  red: "var(--accent-red)",
  cyan: "var(--glow-listening)",
};

interface CollapsibleCardProps {
  title: string;
  icon: ReactNode;
  accent: CollapsibleCardAccent;
  defaultOpen?: boolean;
  children: ReactNode;
}

// The one place every secondary panel on the "Ассистент" page (text
// editing, code analysis, planner, image generation, board games, LAN QR)
// gets its collapsed-by-default, animated, colored card chrome from — see
// the 2026-08-24 redesign plan. Each wrapped panel keeps its own internal
// markup/state untouched; this only supplies the header button + the
// grid-template-rows expand/collapse animation (no JS height measurement,
// no new animation library — same all-CSS approach every other animation
// in this app already uses).
export function CollapsibleCard({ title, icon, accent, defaultOpen = false, children }: CollapsibleCardProps): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  const style = { "--section-accent": ACCENT_VARS[accent] } as CSSProperties;

  return (
    <div className="collapsible-card" style={style}>
      <button
        type="button"
        className={`collapsible-card__header${open ? " collapsible-card__header--open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="collapsible-card__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="collapsible-card__title">{title}</span>
        <span className="collapsible-card__chevron" aria-hidden="true">
          ›
        </span>
      </button>
      <div className={`collapsible-card__body-wrapper${open ? " collapsible-card__body-wrapper--open" : ""}`}>
        <div className="collapsible-card__body">{children}</div>
      </div>
    </div>
  );
}
