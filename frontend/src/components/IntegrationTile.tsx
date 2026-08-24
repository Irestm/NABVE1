import type { CSSProperties, ReactNode } from "react";
import "./IntegrationTile.css";

interface IntegrationTileProps {
  name: string;
  icon: ReactNode;
  brandColor: string;
  active: boolean;
  onClick: () => void;
}

// Just the clickable face (icon + name) — IntegrationsPanel.tsx owns which
// tile is open and renders that one's detail content itself (description/
// download button/ApiKeyField/...), in its own brand-colored panel below
// the whole tile row. Keeping the expanding detail out of this component
// avoids CSS-grid reflow headaches from one grid cell growing tall while
// its siblings don't (see the 2026-08-24 redesign plan).
export function IntegrationTile({ name, icon, brandColor, active, onClick }: IntegrationTileProps): JSX.Element {
  const style = { "--brand-color": brandColor } as CSSProperties;
  return (
    <button
      type="button"
      className={`integration-tile${active ? " integration-tile--active" : ""}`}
      style={style}
      onClick={onClick}
      aria-expanded={active}
    >
      <span className="integration-tile__icon">{icon}</span>
      <span className="integration-tile__name">{name}</span>
    </button>
  );
}
