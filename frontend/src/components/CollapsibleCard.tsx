import { useEffect, useRef, useState } from "react";
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
  // Bump this (e.g. a counter) to force the card open from outside —
  // used by the "Начать шахматы/шашки" system-command shortcut so it can
  // actually reveal the board, not just scroll to a still-collapsed card.
  // Left undefined, the card stays fully self-managed as before.
  openSignal?: number;
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
export function CollapsibleCard({
  title,
  icon,
  accent,
  defaultOpen = false,
  openSignal,
  children,
}: CollapsibleCardProps): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  const style = { "--section-accent": ACCENT_VARS[accent] } as CSSProperties;
  // Compared against on every effect run so mount itself never counts as
  // "the signal changed" — openSignal starts at a defined value (e.g. 0),
  // so a plain `openSignal !== undefined` check forces the card open on
  // every page load. A ref-tracked previous value survives React
  // StrictMode's dev-only double effect invocation on mount too (both
  // invocations compare against the same initial value, so neither opens
  // the card), unlike a simple "first run" boolean flag would.
  const prevSignal = useRef(openSignal);

  useEffect(() => {
    if (openSignal !== undefined && openSignal !== prevSignal.current) {
      setOpen(true);
    }
    prevSignal.current = openSignal;
  }, [openSignal]);

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
