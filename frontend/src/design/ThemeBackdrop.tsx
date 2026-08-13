import type { AssistantState } from "../types";
import { getDesign } from "./registry";
import type { DesignId } from "./types";
import "./ThemeBackdrop.css";

interface ThemeBackdropProps {
  state: AssistantState;
  designId: DesignId;
}

// Full-viewport layer mounted in App.tsx *before* .app-shell, fixed behind
// all cards instead of the old single flat HUD-grid every theme shared (see
// theme.css) — each design's own Background (if any) draws over the whole
// screen here, not just around the avatar. Standard/no-Background designs
// render nothing and simply keep theme.css's grid, which is that design's
// intended background.
export function ThemeBackdrop({ state, designId }: ThemeBackdropProps): JSX.Element | null {
  const design = getDesign(designId);
  const Background = design.Background;
  if (!Background) {
    return null;
  }

  return (
    <div className="theme-backdrop" aria-hidden="true">
      <Background state={state} />
    </div>
  );
}
