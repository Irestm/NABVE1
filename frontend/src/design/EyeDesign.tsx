import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AssistantState } from "../types";
import type { DesignComponentProps } from "./types";
import "./EyeDesign.css";

const BLINK_MIN_MS = 3000;
const BLINK_MAX_MS = 6000;
// Matches the (also lengthened, for smoothness) eye-blink CSS animation
// duration below — keeping the class on for less than the animation's full
// run would cut the reopen short.
const BLINK_DURATION_MS = 320;
const MANUAL_CLOSE_MS = 500;

// Randomized blink timing (3-6s, re-rolled every cycle) instead of a fixed
// looping CSS animation - a real eye doesn't blink on a metronome. Driven
// from JS with setTimeout rather than CSS because varying the *interval*
// itself (not just phase) isn't expressible as a single repeating keyframe.
function useRandomBlink(state: AssistantState): boolean {
  const [blinking, setBlinking] = useState(false);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    function scheduleNext(): void {
      const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
      timeoutRef.current = window.setTimeout(() => {
        setBlinking(true);
        window.setTimeout(() => setBlinking(false), BLINK_DURATION_MS);
        scheduleNext();
      }, delay);
    }
    scheduleNext();
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return state === "paused" ? false : blinking;
}

// Anchor points sampled along the new (bigger, rounder) top lid arc — see
// the eyeball's clip-path quadratic curve in EyeDesign.css — so lashes
// actually sit on the lid edge instead of floating at an arbitrary spot.
// `left`/`top` are the lash <span>'s own top-left (box is 2.4x16px), placed
// so its *bottom* center lands exactly on the arc point; `angle` fans each
// one outward from vertical.
const LASHES: Array<{ left: number; top: number; angle: number }> = [
  { left: 26.8, top: 25, angle: -50 },
  { left: 46.8, top: 17, angle: -24 },
  { left: 66.8, top: 14.5, angle: 0 },
  { left: 86.8, top: 17, angle: 24 },
  { left: 106.8, top: 25, angle: 50 },
];

export function EyeDesign({ state }: DesignComponentProps): JSX.Element {
  const blinking = useRandomBlink(state);
  const [closed, setClosed] = useState(false);
  const closeTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (closeTimeoutRef.current !== null) {
        window.clearTimeout(closeTimeoutRef.current);
      }
    };
  }, []);

  function handleClick(): void {
    setClosed(true);
    if (closeTimeoutRef.current !== null) {
      window.clearTimeout(closeTimeoutRef.current);
    }
    closeTimeoutRef.current = window.setTimeout(() => setClosed(false), MANUAL_CLOSE_MS);
  }

  const stateClass = `eye-design--${state}${blinking ? " eye-design--blinking" : ""}${closed ? " eye-design--closed" : ""}`;

  return (
    <div className={`eye-design ${stateClass}`}>
      <div className="eye-design__nerve eye-design__nerve--1" aria-hidden="true" />
      <div className="eye-design__nerve eye-design__nerve--2" aria-hidden="true" />
      <div className="eye-design__nerve eye-design__nerve--3" aria-hidden="true" />
      <div className="eye-design__nerve eye-design__nerve--4" aria-hidden="true" />
      <button type="button" className="eye-design__socket" onClick={handleClick} aria-label="Моргнуть">
        {/* clip-path'd to a round lens, so every child below is automatically
            cut to the same eye shape - no separate masking needed. */}
        <div className="eye-design__eyeball">
          <div className="eye-design__sclera" />
          <div className="eye-design__vein eye-design__vein--1" />
          <div className="eye-design__vein eye-design__vein--2" />
          <div className="eye-design__vein eye-design__vein--3" />
          <div className="eye-design__vein eye-design__vein--4" />
          <div className="eye-design__vein eye-design__vein--5" />
          <div className="eye-design__iris">
            <div className="eye-design__iris-fiber" />
            <div className="eye-design__pupil" />
            <div className="eye-design__glint eye-design__glint--main" />
            <div className="eye-design__glint eye-design__glint--secondary" />
          </div>
          <div className="eye-design__lid-shadow" />
          <div className="eye-design__lid eye-design__lid--upper" />
          <div className="eye-design__lid eye-design__lid--lower" />
        </div>
        {/* Lashes sit outside the eyeball's clip-path (a sibling, not a
            child of it) so they fan out past the lens boundary instead of
            being cut off by it. */}
        <div className="eye-design__lashes" aria-hidden="true">
          {LASHES.map((lash, index) => (
            <span
              key={index}
              className="eye-design__lash"
              style={{ left: `${lash.left}px`, top: `${lash.top}px`, transform: `rotate(${lash.angle}deg)` } as CSSProperties}
            />
          ))}
        </div>
      </button>
    </div>
  );
}

interface VeinThread {
  top: number;
  left: number;
  length: number;
  angle: number;
  delay: number;
}

const THREAD_COUNT = 24;

function buildThreads(): VeinThread[] {
  const threads: VeinThread[] = [];
  for (let i = 0; i < THREAD_COUNT; i += 1) {
    const seed = i * 53;
    threads.push({
      top: (seed % 101) / 101 * 100,
      left: ((seed * 7) % 97) / 97 * 100,
      length: 60 + (seed % 140),
      angle: (seed * 13) % 360,
      delay: -((seed % 60) / 10),
    });
  }
  return threads;
}

// Dark organic/neural texture behind the whole app shell: thin branching
// "nerve" threads (same visual idea as .eye-design__nerve, scaled up to
// viewport and multiplied) over a few large soft glow nodes, pulsing faster
// and brighter the more active the assistant state is.
export function EyeBackground({ state }: DesignComponentProps): JSX.Element {
  const threads = useMemo(buildThreads, []);

  return (
    <div className={`eye-backdrop eye-backdrop--${state}`}>
      <div className="eye-backdrop__base" />
      <div className="eye-backdrop__node eye-backdrop__node--1" />
      <div className="eye-backdrop__node eye-backdrop__node--2" />
      <div className="eye-backdrop__node eye-backdrop__node--3" />
      {threads.map((thread, index) => (
        <span
          key={index}
          className="eye-backdrop__thread"
          style={{
            top: `${thread.top}%`,
            left: `${thread.left}%`,
            width: `${thread.length}px`,
            transform: `rotate(${thread.angle}deg)`,
            animationDelay: `${thread.delay}s`,
          }}
        />
      ))}
    </div>
  );
}
