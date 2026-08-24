import { Bomb, Flag, PartyPopper, Skull, Smile } from "lucide-react";
import { useEffect, useState } from "react";
// Reuses the shared "nostalgic desktop window" titlebar/dots/LCD-score-
// block chrome instead of duplicating that CSS — same shared/reusable-
// component convention as SolitaireGame.tsx.
import "./GameWindowChrome.css";
import "./MinesweeperGame.css";

// Original Minesweeper implementation — classic rules (grid, adjacent-mine
// counts, flood-fill reveal on a zero) are not copyrightable, no code/art
// borrowed from any existing build (same constraint already applied to
// SolitaireGame.tsx).

interface Cell {
  mine: boolean;
  revealed: boolean;
  flagged: boolean;
  adjacent: number;
}

type Status = "idle" | "playing" | "won" | "lost";
type DifficultyKey = "easy" | "medium" | "hard";

const DIFFICULTIES: Record<DifficultyKey, { rows: number; cols: number; mines: number; label: string }> = {
  easy: { rows: 9, cols: 9, mines: 10, label: "Лёгкий" },
  medium: { rows: 12, cols: 12, mines: 20, label: "Средний" },
  hard: { rows: 16, cols: 16, mines: 40, label: "Сложный" },
};

const NUMBER_COLOR: Record<number, string> = {
  1: "#4f8dff",
  2: "#3fae4a",
  3: "#e0453f",
  4: "#7a3fd9",
  5: "#b5402f",
  6: "#2ad8ff",
  7: "#e8e8ec",
  8: "#9aa4b8",
};

function emptyGrid(rows: number, cols: number): Cell[][] {
  return Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => ({ mine: false, revealed: false, flagged: false, adjacent: 0 })),
  );
}

function buildGrid(rows: number, cols: number, mineCount: number, safeRow: number, safeCol: number): Cell[][] {
  const cells = emptyGrid(rows, cols);
  const forbidden = new Set<string>();
  for (let dr = -1; dr <= 1; dr++) {
    for (let dc = -1; dc <= 1; dc++) {
      const r = safeRow + dr;
      const c = safeCol + dc;
      if (r >= 0 && r < rows && c >= 0 && c < cols) forbidden.add(`${r},${c}`);
    }
  }
  let placed = 0;
  while (placed < mineCount) {
    const r = Math.floor(Math.random() * rows);
    const c = Math.floor(Math.random() * cols);
    const key = `${r},${c}`;
    if (forbidden.has(key) || cells[r][c].mine) continue;
    cells[r][c].mine = true;
    placed++;
  }
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (cells[r][c].mine) continue;
      let count = 0;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (dr === 0 && dc === 0) continue;
          const nr = r + dr;
          const nc = c + dc;
          if (nr >= 0 && nr < rows && nc >= 0 && nc < cols && cells[nr][nc].mine) count++;
        }
      }
      cells[r][c].adjacent = count;
    }
  }
  return cells;
}

function revealFlood(grid: Cell[][], row: number, col: number, rows: number, cols: number): Cell[][] {
  const next = grid.map((r) => r.map((c) => ({ ...c })));
  const stack: Array<[number, number]> = [[row, col]];
  const seen = new Set<string>();
  while (stack.length > 0) {
    const [r, c] = stack.pop()!;
    const key = `${r},${c}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const cell = next[r][c];
    if (cell.revealed || cell.flagged) continue;
    cell.revealed = true;
    if (cell.adjacent === 0 && !cell.mine) {
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (dr === 0 && dc === 0) continue;
          const nr = r + dr;
          const nc = c + dc;
          if (nr >= 0 && nr < rows && nc >= 0 && nc < cols && !next[nr][nc].revealed) stack.push([nr, nc]);
        }
      }
    }
  }
  return next;
}

export function MinesweeperGame(): JSX.Element {
  const [difficulty, setDifficulty] = useState<DifficultyKey>("easy");
  const { rows, cols, mines } = DIFFICULTIES[difficulty];
  const [grid, setGrid] = useState<Cell[][]>(() => emptyGrid(rows, cols));
  const [status, setStatus] = useState<Status>("idle");
  const [flagMode, setFlagMode] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (status !== "playing" || startTime === null) return;
    const id = window.setInterval(() => setElapsed(Math.min(999, Math.floor((Date.now() - startTime) / 1000))), 250);
    return () => window.clearInterval(id);
  }, [status, startTime]);

  function newGame(next: DifficultyKey) {
    const preset = DIFFICULTIES[next];
    setDifficulty(next);
    setGrid(emptyGrid(preset.rows, preset.cols));
    setStatus("idle");
    setFlagMode(false);
    setStartTime(null);
    setElapsed(0);
  }

  function flagsUsed(g: Cell[][]): number {
    return g.reduce((sum, r) => sum + r.filter((c) => c.flagged).length, 0);
  }

  function checkWin(g: Cell[][]) {
    const revealedSafe = g.reduce((sum, r) => sum + r.filter((c) => c.revealed && !c.mine).length, 0);
    if (revealedSafe === rows * cols - mines) setStatus("won");
  }

  function toggleFlag(row: number, col: number) {
    setGrid((prev) => {
      const next = prev.map((r) => r.map((c) => ({ ...c })));
      next[row][col].flagged = !next[row][col].flagged;
      return next;
    });
  }

  function onCellClick(row: number, col: number) {
    if (status === "won" || status === "lost") return;
    const cell = grid[row][col];
    if (flagMode) {
      if (cell.revealed) return;
      toggleFlag(row, col);
      return;
    }
    if (cell.flagged || cell.revealed) return;

    if (status === "idle") {
      const seeded = buildGrid(rows, cols, mines, row, col);
      const revealed = revealFlood(seeded, row, col, rows, cols);
      setGrid(revealed);
      setStatus("playing");
      setStartTime(Date.now());
      checkWin(revealed);
      return;
    }

    if (cell.mine) {
      const next = grid.map((r, ri) =>
        r.map((c, ci) => (c.mine ? { ...c, revealed: true } : ri === row && ci === col ? { ...c, revealed: true } : c)),
      );
      setGrid(next);
      setStatus("lost");
      return;
    }

    const revealed = revealFlood(grid, row, col, rows, cols);
    setGrid(revealed);
    checkWin(revealed);
  }

  function onCellContextMenu(event: React.MouseEvent, row: number, col: number) {
    event.preventDefault();
    if (status === "won" || status === "lost") return;
    if (grid[row][col].revealed) return;
    toggleFlag(row, col);
  }

  const remaining = mines - flagsUsed(grid);
  const FaceIcon = status === "lost" ? Skull : status === "won" ? PartyPopper : Smile;

  return (
    <div className="minesweeper-window">
      <div className="game-window__titlebar">
        <span className="game-window__title">Сапёр</span>
        <div className="game-window__dots">
          <span className="game-window__dot game-window__dot--min" />
          <span className="game-window__dot game-window__dot--max" />
          <span className="game-window__dot game-window__dot--close" />
        </div>
      </div>

      <div className="minesweeper-window__toolbar">
        {(Object.keys(DIFFICULTIES) as DifficultyKey[]).map((key) => (
          <button
            key={key}
            type="button"
            className={`minesweeper-window__diff-btn${key === difficulty ? " minesweeper-window__diff-btn--active" : ""}`}
            onClick={() => newGame(key)}
          >
            {DIFFICULTIES[key].label}
          </button>
        ))}
        <button
          type="button"
          className={`minesweeper-window__flag-btn${flagMode ? " minesweeper-window__flag-btn--active" : ""}`}
          onClick={() => setFlagMode((v) => !v)}
          title="Режим расстановки флажков (для сенсорного экрана)"
        >
          <Flag size={16} />
        </button>
      </div>

      <div className="minesweeper-window__scoreboard">
        <div className="game-window__score-block">
          <span className="game-window__score-label">Мины</span>
          <span className="game-window__score-value">{String(Math.max(0, remaining)).padStart(3, "0")}</span>
        </div>
        <button type="button" className="minesweeper-window__face" onClick={() => newGame(difficulty)}>
          <FaceIcon size={20} />
        </button>
        <div className="game-window__score-block">
          <span className="game-window__score-label">Время</span>
          <span className="game-window__score-value">{String(elapsed).padStart(3, "0")}</span>
        </div>
      </div>

      <div className="minesweeper-window__board-scroll">
        <div
          className="minesweeper-window__grid"
          style={{ gridTemplateColumns: `repeat(${cols}, 48px)`, gridTemplateRows: `repeat(${rows}, 48px)` }}
        >
          {grid.map((r, ri) =>
            r.map((cell, ci) => {
              const key = `${ri}-${ci}`;
              if (!cell.revealed) {
                return (
                  <button
                    key={key}
                    type="button"
                    className="minesweeper-cell minesweeper-cell--covered"
                    onClick={() => onCellClick(ri, ci)}
                    onContextMenu={(event) => onCellContextMenu(event, ri, ci)}
                  >
                    {cell.flagged && <Flag size={26} />}
                  </button>
                );
              }
              return (
                <div
                  key={key}
                  className={`minesweeper-cell minesweeper-cell--open${cell.mine ? " minesweeper-cell--mine" : ""}`}
                >
                  {cell.mine ? (
                    <Bomb size={26} />
                  ) : cell.adjacent > 0 ? (
                    <span style={{ color: NUMBER_COLOR[cell.adjacent] }}>{cell.adjacent}</span>
                  ) : null}
                </div>
              );
            }),
          )}
        </div>
      </div>

      {status === "won" && (
        <div className="game-window__overlay">
          <p className="game-window__overlay-title">Победа!</p>
          <p className="game-window__overlay-score">Время: {elapsed} с</p>
          <button type="button" className="minesweeper-window__diff-btn" onClick={() => newGame(difficulty)}>
            Новая игра
          </button>
        </div>
      )}
      {status === "lost" && (
        <div className="game-window__overlay">
          <p className="game-window__overlay-title">Подрыв!</p>
          <button type="button" className="minesweeper-window__diff-btn" onClick={() => newGame(difficulty)}>
            Новая игра
          </button>
        </div>
      )}
    </div>
  );
}
