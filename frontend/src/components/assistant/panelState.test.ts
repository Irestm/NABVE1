import { describe, expect, it } from "vitest";
import { DEFAULT_PANEL_WIDTH, clampWidth, isNarrow, maxPanelWidth, normalizeState } from "./panelState";

describe("panel width", () => {
  it("clamps to 280px minimum and 60% of the window maximum", () => {
    expect(clampWidth(100, 1400)).toBe(280);
    expect(clampWidth(2000, 1400)).toBe(840);
    expect(clampWidth(500, 1400)).toBe(500);
    expect(maxPanelWidth(1000)).toBe(600);
  });

  it("falls back to the default width for garbage", () => {
    expect(clampWidth(Number.NaN, 1400)).toBe(DEFAULT_PANEL_WIDTH);
    expect(normalizeState({ open: "yes", width: "wide" })).toEqual({ open: false, width: DEFAULT_PANEL_WIDTH });
    expect(normalizeState({ open: true, width: 512 })).toEqual({ open: true, width: 512 });
  });

  it("treats windows under 900px as narrow", () => {
    expect(isNarrow(899)).toBe(true);
    expect(isNarrow(900)).toBe(false);
  });
});
