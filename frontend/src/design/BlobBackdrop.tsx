import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import type { DesignId } from "./types";
import "./BlobBackdrop.css";

// Designs with their own fully-styled, ownership-of-the-whole-screen
// Background (ThemeBackdrop.tsx) — Pixel's mosaic grid and Clown's rig
// would both fight visually with two huge drifting glows, so this layer is
// deliberately skipped for them (explicit user request). Every other
// design (including "standard", which has no Background of its own) gets
// it, layered on top of that design's own backdrop via mix-blend-mode
// rather than editing each one individually.
const EXCLUDED_DESIGNS: ReadonlySet<DesignId> = new Set(["pixel", "clown"]);

interface BlobColorPair {
  a: string;
  b: string;
}

// Default (blue/red) covers "standard" and any design not listed here
// (currently "eye") — the three below got an explicit per-theme palette
// request instead of the generic blue/red.
const BLOB_COLORS: Partial<Record<DesignId, BlobColorPair>> = {
  sun: { a: "#ffd60a", b: "#ff8c00" }, // жёлтый + оранж
  cloud_calm: { a: "#3b6bff", b: "#9b30ff" }, // синий + фиолетовый
  cloud_green: { a: "#ffd60a", b: "#6b8e23" }, // жёлтый + болотный
};

const DEFAULT_COLORS: BlobColorPair = { a: "#2f6dff", b: "#ff3b3b" };

// The blobs' own colors never change (explicit follow-up: "цвета
// остаются те же") — only the zone where they actually overlap gets a
// dedicated neon-purple glow, via a third element (see
// blob-backdrop__merge-glow below) rather than by changing what color
// the blobs themselves are.
const MERGE_GLOW_COLOR = "#b400ff";
// The glow only ramps in for the final stretch of the approach — it's a
// payoff for "они смешиваются", not something visible from the start.
const MERGE_GLOW_START = 0.55;

// Slow, and slowing down further as it approaches (eased radius) rather
// than a constant crawl the whole way — matches the explicit
// "медленнее... и когда приближаются ещё замедляются" request.
const SPIRAL_DURATION_MS = 3400;
// The spiral twist itself only kicks in for the back half of the
// approach (see SPIRAL_START below) — from far away the blobs mostly
// just close distance; the visible "spinning into each other" happens
// once they're already close, which reads as more deliberate than
// spiraling for the entire multi-second travel.
const SPIRAL_START = 0.35;
const SPIRAL_TURNS = 1.75;

// Slow-fast-slow rather than easeOutQuint's fast-start — a pure ease-out
// covered most of the distance in the first third of the duration, which
// read as a quick dash followed by a long crawl rather than "slow the
// whole way, slower still at the end" like the user actually asked for.
function easeInOutQuint(t: number): number {
  return t < 0.5 ? 16 * Math.pow(t, 5) : 1 - Math.pow(-2 * t + 2, 5) / 2;
}

interface BlobBackdropProps {
  designId: DesignId;
  // Set (screen coords) while the Gojo easter egg is held on the "eye"
  // design — see useGojoEasterEgg. Both blobs spiral into the same point
  // instead of their usual drift, so they visibly merge into one blended
  // (purple, via the existing screen-blend) spot right under the cursor.
  convergeTo?: { x: number; y: number } | null;
  // Called once the spiral-in animation actually finishes (not just when
  // convergeTo is set) — see useGojoEasterEgg's notifyConverged.
  onConverged?: () => void;
}

export function BlobBackdrop({ designId, convergeTo, onConverged }: BlobBackdropProps): JSX.Element | null {
  const blobARef = useRef<HTMLDivElement>(null);
  const blobBRef = useRef<HTMLDivElement>(null);
  const mergeGlowRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    function cancelSpiral(): void {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    }

    if (!convergeTo) {
      cancelSpiral();
      // Clears every inline override at once — falls straight back to the
      // stylesheet's corner position + chaotic-drift keyframes, no
      // per-property bookkeeping needed on the way out.
      for (const ref of [blobARef, blobBRef]) {
        if (ref.current) {
          ref.current.style.cssText = "";
        }
      }
      if (mergeGlowRef.current) {
        mergeGlowRef.current.style.cssText = "";
      }
      return;
    }

    const target = convergeTo;
    const entries = [
      { ref: blobARef, direction: 1 },
      { ref: blobBRef, direction: -1 },
    ] as const;

    // Real on-screen position at the moment of press (mid chaotic-drift,
    // not the CSS's static corner values) — measured once, before any
    // inline overrides are applied, so the switch to spiral motion starts
    // exactly where the blob visually already was.
    const starts = entries.map(({ ref }) => {
      const el = ref.current;
      if (!el) {
        return { x: target.x, y: target.y };
      }
      const rect = el.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });

    for (const { ref } of entries) {
      const el = ref.current;
      if (!el) {
        continue;
      }
      el.style.position = "fixed";
      el.style.right = "auto";
      el.style.bottom = "auto";
      el.style.transform = "translate(-50%, -50%)";
      el.style.animation = "none";
      el.style.transition = "none";
    }

    // The glow sits fixed at `target` the whole time (both blobs
    // converge on that exact same point, so that's where they actually
    // meet) — only its opacity animates, ramping in for the final
    // stretch of the approach.
    if (mergeGlowRef.current) {
      const el = mergeGlowRef.current;
      el.style.position = "fixed";
      el.style.left = `${target.x}px`;
      el.style.top = `${target.y}px`;
      el.style.transform = "translate(-50%, -50%)";
      el.style.transition = "none";
      el.style.opacity = "0";
    }

    const startTime = performance.now();

    function tick(now: number): void {
      const t = Math.min(1, (now - startTime) / SPIRAL_DURATION_MS);
      const radiusT = easeInOutQuint(t);
      const spiralProgress = Math.max(0, Math.min(1, (t - SPIRAL_START) / (1 - SPIRAL_START)));
      const spiralEase = spiralProgress * spiralProgress;

      entries.forEach(({ ref, direction }, index) => {
        const el = ref.current;
        if (!el) {
          return;
        }
        const start = starts[index];
        const dx = target.x - start.x;
        const dy = target.y - start.y;
        const dist = Math.hypot(dx, dy);
        // Angle from the TARGET back toward start (+PI), not start toward
        // target — the real bug behind the teleport: at t=0 the old angle
        // (baseAngle with no +PI) placed the blob at target + dist*(unit
        // vector FROM start TO target), i.e. the mirror image of `start`
        // reflected through `target`, not `start` itself. Radius still
        // shrinks to 0 at t=1 regardless of this offset, so convergence on
        // the target is unaffected — this only fixes where t=0 lands.
        const baseAngle = Math.atan2(dy, dx) + Math.PI;
        const radius = dist * (1 - radiusT);
        const angle = baseAngle + direction * spiralEase * SPIRAL_TURNS * Math.PI * 2;
        el.style.left = `${target.x + Math.cos(angle) * radius}px`;
        el.style.top = `${target.y + Math.sin(angle) * radius}px`;
      });

      if (mergeGlowRef.current) {
        const glowProgress = Math.max(0, Math.min(1, (t - MERGE_GLOW_START) / (1 - MERGE_GLOW_START)));
        mergeGlowRef.current.style.opacity = String(glowProgress * glowProgress);
      }

      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = null;
        onConverged?.();
      }
    }

    // Called synchronously (not via requestAnimationFrame) so the very
    // first paint after switching to position:fixed already has left/top
    // set to the measured start position — scheduling the first tick via
    // rAF left a one-frame gap where the element had no inline left/top
    // yet and fell back to the stylesheet's static corner values, which
    // read as a sudden jump before the spiral "corrected" itself a frame
    // later. At t=0 the formula below always resolves to exactly `start`
    // anyway, so this is just removing that one bad frame, not changing
    // the motion itself.
    tick(startTime);

    return () => {
      cancelSpiral();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convergeTo]);

  if (EXCLUDED_DESIGNS.has(designId)) {
    return null;
  }

  const colors = BLOB_COLORS[designId] ?? DEFAULT_COLORS;
  const style = { "--blob-color-a": colors.a, "--blob-color-b": colors.b } as CSSProperties;

  return (
    <div className="blob-backdrop" style={style} aria-hidden="true">
      <div ref={blobARef} className="blob-backdrop__blob blob-backdrop__blob--a">
        <div className="blob-backdrop__blob-inner blob-backdrop__blob-inner--a" />
      </div>
      <div ref={blobBRef} className="blob-backdrop__blob blob-backdrop__blob--b">
        <div className="blob-backdrop__blob-inner blob-backdrop__blob-inner--b" />
      </div>
      {designId === "eye" && (
        <div
          ref={mergeGlowRef}
          className="blob-backdrop__merge-glow"
          style={{ "--merge-glow-color": MERGE_GLOW_COLOR } as CSSProperties}
        />
      )}
    </div>
  );
}
