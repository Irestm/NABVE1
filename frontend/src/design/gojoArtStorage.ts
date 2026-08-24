const STORAGE_KEY = "gojoEasterEggArt";

// Purely local read for the "eye" design's Gojo easter egg (see
// GojoOverlay.tsx) — whatever image already sits under this key in this
// browser's localStorage (set once, previously, via the now-removed
// upload UI) is what's shown; there's no more in-app way to add, replace,
// or clear it, by explicit request. Read on every GojoOverlay mount
// rather than kept live in React state anywhere, since the overlay only
// mounts transiently (while the easter egg is held).
export function readGojoArt(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    console.error("Failed to read the stored Gojo easter-egg art:", error);
    return null;
  }
}
