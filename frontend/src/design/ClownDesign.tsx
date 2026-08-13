import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { DesignComponentProps } from "./types";
import "./ClownDesign.css";

const HONK_DURATION_MS = 2600;

// Synthesized on the fly (a quick square-wave sweep) instead of shipping an
// audio asset — this is a one-off easter-egg honk, not real TTS, so a Web
// Audio oscillator is simpler than adding a file to bundle/package.
function playSqueak(): void {
  try {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "square";
    oscillator.frequency.setValueAtTime(320, context.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(980, context.currentTime + 0.12);
    oscillator.frequency.exponentialRampToValueAtTime(260, context.currentTime + 0.3);
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.22, context.currentTime + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.34);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.36);
    oscillator.onended = () => void context.close();
  } catch {
    // Web Audio unavailable (blocked autoplay policy, etc.) — the rainbow
    // flash below still fires, so the easter egg isn't entirely silent-fail.
  }
}

// Reference clown wigs (Chicago Costume Co., Halloween Costumes, Candy Apple
// Costumes etc.) are a dense, round, high-volume mass of tight curls with no
// visible gaps - a handful of sparse circles reads as "a few balloons", not
// "a wig". This lays curls out in concentric rings around a center point so
// the cluster fills in solid and round, the way a real curly wig does; each
// side uses the exact same layout (unmirrored) since a filled round poof
// looks identical either way, which also sidesteps the mirroring bugs the
// two-circle version had.
interface WigCurl {
  x: number;
  y: number;
  size: number;
  variant: number;
}

const WIG_RINGS: Array<{ radius: number; count: number; minSize: number; maxSize: number }> = [
  { radius: 0, count: 1, minSize: 30, maxSize: 30 },
  { radius: 15, count: 5, minSize: 27, maxSize: 31 },
  { radius: 29, count: 8, minSize: 21, maxSize: 26 },
  { radius: 40, count: 7, minSize: 16, maxSize: 20 },
];

function buildWigCurls(): WigCurl[] {
  const curls: WigCurl[] = [];
  let index = 0;
  for (const ring of WIG_RINGS) {
    for (let i = 0; i < ring.count; i += 1) {
      const angle = (i / ring.count) * Math.PI * 2 + ring.radius * 0.015;
      const spread = ring.count > 1 ? (index % ring.count) / ring.count : 0;
      const size = ring.minSize + (ring.maxSize - ring.minSize) * spread;
      curls.push({
        x: Math.cos(angle) * ring.radius,
        y: Math.sin(angle) * ring.radius * 0.94,
        size,
        variant: index % 3,
      });
      index += 1;
    }
  }
  return curls;
}

const CONFETTI_COLORS = ["#ff3d5a", "#ffb703", "#06d6a0", "#c77dff", "#ffd166", "#4cc9f0"];
const CONFETTI_COUNT = 24;
const STREAMER_COLORS = ["#ff3d5a", "#ffb703", "#06d6a0", "#c77dff", "#4cc9f0", "#ff8fab"];
// Dense, top-heavy canopy — "больше ленточек сверху": every ribbon already
// hangs from the top edge, so more of them (and a wider length spread) is
// what actually reads as a full streamer canopy instead of a few stray
// strands.
const STREAMER_COUNT = 14;

interface ConfettiPiece {
  left: number;
  delay: number;
  duration: number;
  color: string;
  size: number;
  rotate: number;
  drift: number;
}

function buildConfetti(): ConfettiPiece[] {
  const pieces: ConfettiPiece[] = [];
  for (let i = 0; i < CONFETTI_COUNT; i += 1) {
    // Deterministic pseudo-randomness (no Math.random) so server/client and
    // repeated mounts render identically instead of reshuffling every time.
    const seed = i * 37;
    pieces.push({
      left: (seed % 97) / 97 * 100,
      delay: -((seed % 53) / 53) * 9,
      duration: 7 + ((seed % 29) / 29) * 5,
      color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
      size: 6 + (seed % 11),
      rotate: (seed % 360),
      drift: ((seed % 7) - 3) * 12,
    });
  }
  return pieces;
}

interface StreamerRibbon {
  left: number;
  color: string;
  delay: number;
  length: number;
}

function buildStreamers(): StreamerRibbon[] {
  const ribbons: StreamerRibbon[] = [];
  for (let i = 0; i < STREAMER_COUNT; i += 1) {
    // Deterministic seed (not Math.random — same reasoning as buildConfetti)
    // jitters the even spacing a little so ribbons don't line up in a
    // perfectly uniform row.
    const seed = i * 29;
    ribbons.push({
      left: (i / (STREAMER_COUNT - 1)) * 96 + 1 + ((seed % 7) - 3),
      color: STREAMER_COLORS[i % STREAMER_COLORS.length],
      delay: -((seed % 47) / 10),
      length: 90 + (seed % 190),
    });
  }
  return ribbons;
}

export function ClownDesign({ state }: DesignComponentProps): JSX.Element {
  const [honking, setHonking] = useState(false);
  const timeoutRef = useRef<number | null>(null);
  const curls = useMemo(buildWigCurls, []);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  function handleHonk(): void {
    playSqueak();
    setHonking(true);
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = window.setTimeout(() => setHonking(false), HONK_DURATION_MS);
  }

  function renderWig(side: "left" | "right"): JSX.Element {
    return (
      <div className={`clown-design__wig clown-design__wig--${side}`} aria-hidden="true">
        {curls.map((curl, index) => {
          const style: CSSProperties = {
            left: `calc(50% + ${curl.x}px - ${curl.size / 2}px)`,
            top: `calc(50% + ${curl.y}px - ${curl.size / 2}px)`,
            width: `${curl.size}px`,
            height: `${curl.size}px`,
          };
          return <span key={index} className={`clown-design__wig-curl clown-design__wig-curl--v${curl.variant}`} style={style} />;
        })}
      </div>
    );
  }

  return (
    <div className={`clown-design clown-design--${state}${honking ? " clown-design--honking" : ""}`}>
      {renderWig("left")}
      {renderWig("right")}
      {/* A literal clown face (🤡-style) instead of a nose floating between
          two hair puffs: skin, white greasepaint patches, eyes, blush and a
          painted smile, all centered behind the interactive nose. */}
      <div className="clown-design__face" aria-hidden="true">
        <span className="clown-design__patch clown-design__patch--left" />
        <span className="clown-design__patch clown-design__patch--right" />
        <span className="clown-design__eye clown-design__eye--left" />
        <span className="clown-design__eye clown-design__eye--right" />
        <span className="clown-design__cheek clown-design__cheek--left" />
        <span className="clown-design__cheek clown-design__cheek--right" />
        <span className="clown-design__mouth" />
      </div>
      <button
        type="button"
        className="clown-design__nose"
        onClick={handleHonk}
        aria-label="Нос клоуна — нажми, чтобы пискнул"
        title="Нажми на нос!"
      >
        <span className="clown-design__nose-shine" aria-hidden="true" />
      </button>
    </div>
  );
}

// Circus tent stripes + falling confetti + hanging streamer ribbons behind
// the whole app shell (see ThemeBackdrop). Confetti/streamer layouts are
// generated once with useMemo, same approach as buildWigCurls above.
export function ClownBackground({ state }: DesignComponentProps): JSX.Element {
  const confetti = useMemo(buildConfetti, []);
  const streamers = useMemo(buildStreamers, []);

  return (
    <div className={`clown-backdrop clown-backdrop--${state}`}>
      <div className="clown-backdrop__stripes" />
      {streamers.map((ribbon, index) => {
        const style: CSSProperties = {
          left: `${ribbon.left}%`,
          height: `${ribbon.length}px`,
          animationDelay: `${ribbon.delay}s`,
          background: `repeating-linear-gradient(180deg, ${ribbon.color} 0 10px, #fff8 10px 12px, ${ribbon.color} 12px 22px)`,
        };
        return <div key={index} className="clown-backdrop__streamer" style={style} />;
      })}
      {confetti.map((piece, index) => {
        const style: CSSProperties = {
          left: `${piece.left}%`,
          width: `${piece.size}px`,
          height: `${piece.size * 0.6}px`,
          backgroundColor: piece.color,
          animationDelay: `${piece.delay}s`,
          animationDuration: `${piece.duration}s`,
          "--confetti-rotate": `${piece.rotate}deg`,
          "--confetti-drift": `${piece.drift}px`,
        } as CSSProperties;
        return <span key={index} className="clown-backdrop__confetti" style={style} />;
      })}
    </div>
  );
}
