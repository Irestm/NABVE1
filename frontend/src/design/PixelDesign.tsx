import { useMemo, type CSSProperties } from "react";
import type { DesignComponentProps } from "./types";
import "./PixelDesign.css";

// Dense on purpose — point 4 of the design-picker request asked for "as
// dense as possible" pixel art, so cells are drawn edge-to-edge (no gap)
// at a small enough grid size that it reads as a textured blob, not a
// blocky low-res circle.
const GRID_SIZE = 18;

interface PixelCell {
  x: number;
  y: number;
  delay: number;
  variant: 0 | 1 | 2;
}

function buildGrid(): PixelCell[] {
  const cells: PixelCell[] = [];
  const center = (GRID_SIZE - 1) / 2;
  const radius = GRID_SIZE / 2 - 0.4;
  for (let y = 0; y < GRID_SIZE; y += 1) {
    for (let x = 0; x < GRID_SIZE; x += 1) {
      const dx = x - center;
      const dy = y - center;
      if (Math.sqrt(dx * dx + dy * dy) <= radius) {
        cells.push({
          x,
          y,
          delay: ((x * 7 + y * 13) % 23) / 10,
          variant: ((x + y * 3) % 3) as 0 | 1 | 2,
        });
      }
    }
  }
  return cells;
}

const CELL_SIZE = 100 / GRID_SIZE;

export function PixelDesign({ state }: DesignComponentProps): JSX.Element {
  const cells = useMemo(buildGrid, []);

  return (
    <div className={`pixel-design pixel-design--${state}`} aria-hidden="true">
      <div className="pixel-design__grid">
        {cells.map((cell) => {
          const style: CSSProperties = {
            left: `${cell.x * CELL_SIZE}%`,
            top: `${cell.y * CELL_SIZE}%`,
            width: `${CELL_SIZE}%`,
            height: `${CELL_SIZE}%`,
            animationDelay: `${cell.delay}s`,
          };
          return (
            <span key={`${cell.x}-${cell.y}`} className={`pixel-design__cell pixel-design__cell--v${cell.variant}`} style={style} />
          );
        })}
      </div>
    </div>
  );
}

// Full-screen dithered pixel-grid backdrop — two stacked low-res checker
// patterns at different scales fake an 8-bit dither instead of the app's
// generic HUD grid (see ThemeBackdrop).
export function PixelBackground({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`pixel-backdrop pixel-backdrop--${state}`}>
      <div className="pixel-backdrop__base" />
      <div className="pixel-backdrop__dither" />
    </div>
  );
}
