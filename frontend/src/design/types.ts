import type { AssistantState } from "../types";

// Stable ids — persisted to localStorage (see AssistantAvatar/SettingsPanel),
// so renaming one silently resets every existing user back to the default
// design. Add new ones; don't rename existing ones.
export type DesignId = "standard" | "sun" | "clown" | "cloud_green" | "pixel" | "eye" | "cloud_calm";

export interface DesignComponentProps {
  state: AssistantState;
}

export interface DesignDefinition {
  id: DesignId;
  name: string;
  tagline: string;
  description: string;
  Component: (props: DesignComponentProps) => JSX.Element;
  // Full-viewport backdrop mounted behind .app-shell (see ThemeBackdrop) —
  // optional because not every design needs more than theme.css's palette
  // swap; the 6 non-standard designs all provide one so their background
  // stops falling back to the generic HUD grid.
  Background?: (props: DesignComponentProps) => JSX.Element;
}
