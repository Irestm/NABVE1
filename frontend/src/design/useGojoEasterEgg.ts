import { useCallback, useEffect, useRef, useState } from "react";
import type { DesignId } from "./types";

// A plain click (mousedown immediately followed by mouseup, e.g. clicking
// any ordinary button) shouldn't trigger this at all — only a genuine
// press-and-hold should. convergeTo only gets set once the button has
// been held this long without releasing.
const HOLD_BEFORE_TRIGGER_MS = 2000;

export interface GojoEasterEggState {
  convergeTo: { x: number; y: number } | null;
  merged: boolean;
  // Called by BlobBackdrop once its own spiral-in animation actually
  // finishes — the timing lives entirely there now (eased, several
  // seconds, not a fixed duration this hook would otherwise have to
  // duplicate and keep in sync by hand).
  notifyConverged: () => void;
}

// Easter egg exclusive to the "eye" design (explicit user request) — press
// and hold anywhere on the page for 3s: the two background blobs
// (BlobBackdrop) spiral in on the cursor instead of their usual chaotic
// drift, and once they've actually finished (BlobBackdrop calls
// notifyConverged), GojoOverlay swaps in for the theme's single eye.
// Releasing anywhere — before or after the hold threshold — reverts
// everything immediately. Lives as its own hook rather than inline in
// App.tsx since it owns real event-listener lifecycle, not just a couple
// of state fields, and both BlobBackdrop and the stage need the result.
export function useGojoEasterEgg(designId: DesignId): GojoEasterEggState {
  const [convergeTo, setConvergeTo] = useState<{ x: number; y: number } | null>(null);
  const [merged, setMerged] = useState(false);
  const holdTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    if (designId !== "eye") {
      return;
    }

    function clearHoldTimeout(): void {
      if (holdTimeoutRef.current !== null) {
        window.clearTimeout(holdTimeoutRef.current);
        holdTimeoutRef.current = null;
      }
    }

    function handleDown(event: MouseEvent): void {
      // Left button only — a right/middle-click shouldn't trigger it.
      if (event.button !== 0) {
        return;
      }
      const { clientX, clientY } = event;
      clearHoldTimeout();
      holdTimeoutRef.current = window.setTimeout(() => {
        holdTimeoutRef.current = null;
        setMerged(false);
        setConvergeTo({ x: clientX, y: clientY });
      }, HOLD_BEFORE_TRIGGER_MS);
    }

    function handleUp(): void {
      clearHoldTimeout();
      setConvergeTo(null);
      setMerged(false);
    }

    window.addEventListener("mousedown", handleDown);
    window.addEventListener("mouseup", handleUp);
    return () => {
      clearHoldTimeout();
      window.removeEventListener("mousedown", handleDown);
      window.removeEventListener("mouseup", handleUp);
      setConvergeTo(null);
      setMerged(false);
    };
  }, [designId]);

  const notifyConverged = useCallback(() => setMerged(true), []);

  return { convergeTo, merged, notifyConverged };
}
