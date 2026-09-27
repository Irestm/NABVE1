export const MIN_PANEL_WIDTH = 280;
export const MAX_PANEL_SHARE = 0.6;
export const DEFAULT_PANEL_WIDTH = 380;
export const NARROW_WINDOW = 900;

export interface PanelState {
  open: boolean;
  width: number;
}

export const DEFAULT_PANEL_STATE: PanelState = { open: false, width: DEFAULT_PANEL_WIDTH };

export function maxPanelWidth(windowWidth: number): number {
  return Math.max(MIN_PANEL_WIDTH, Math.floor(windowWidth * MAX_PANEL_SHARE));
}

export function clampWidth(width: number, windowWidth: number): number {
  if (!Number.isFinite(width)) {
    return DEFAULT_PANEL_WIDTH;
  }
  return Math.round(Math.min(maxPanelWidth(windowWidth), Math.max(MIN_PANEL_WIDTH, width)));
}

export function isNarrow(windowWidth: number): boolean {
  return windowWidth < NARROW_WINDOW;
}

export function normalizeState(value: unknown): PanelState {
  if (typeof value !== "object" || value === null) {
    return DEFAULT_PANEL_STATE;
  }
  const raw = value as Partial<PanelState>;
  return {
    open: typeof raw.open === "boolean" ? raw.open : DEFAULT_PANEL_STATE.open,
    width: typeof raw.width === "number" && Number.isFinite(raw.width) ? raw.width : DEFAULT_PANEL_WIDTH,
  };
}

export interface PanelStore {
  load(): Promise<PanelState>;
  save(state: PanelState): Promise<void>;
}
