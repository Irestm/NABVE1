import { Bomb, Crown } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { finishBoardGame, getCurrentBoardGame, playBoardGameMove, startBoardGame } from "../api/client";
import type { BoardGameDifficulty, BoardGameKind, BoardGameState } from "../types";
import { CheckersIcon } from "./CheckersIcon";
import { MinesweeperGame } from "./MinesweeperGame";
import { SolitaireGame } from "./SolitaireGame";
import { SolitaireIcon } from "./SolitaireIcon";
import "./BoardGamesPanel.css";

// Same icon choice as core/command_ui_metadata.py's "Crown"/"CheckersGlyph"
// for the matching System Commands shortcuts — a crown for the queen
// (no dedicated chess-queen icon exists in lucide-react) and the hand-drawn
// two-tone piece pair for checkers, instead of a generic Gamepad glyph.
const KIND_ICON: Record<BoardGameKind, (props: { size?: number }) => ReactNode> = {
  chess: Crown,
  checkers: CheckersIcon,
};

const KIND_LABEL: Record<BoardGameKind, string> = {
  chess: "Шахматы",
  checkers: "Шашки",
};

// Order matters here — rendered left-to-right as the difficulty chip row.
// 10 levels now (was 6) — a new tier inserted between each original pair,
// explicit request: "чуть выше лёгкого, потом средний, чуть ниже
// сложного и т.д." Mirrors modules/board_games/domain.py's Difficulty
// enum member order exactly.
const DIFFICULTY_OPTIONS: BoardGameDifficulty[] = [
  "very_easy",
  "easy",
  "easy_plus",
  "medium",
  "medium_plus",
  "hard",
  "hard_plus",
  "very_hard",
  "very_hard_plus",
  "impossible",
];

const DIFFICULTY_LABEL: Record<BoardGameDifficulty, string> = {
  very_easy: "Очень легко",
  easy: "Легко",
  easy_plus: "Чуть выше лёгкого",
  medium: "Средне",
  medium_plus: "Чуть выше среднего",
  hard: "Сложно",
  hard_plus: "Чуть выше сложного",
  very_hard: "Очень сложно",
  very_hard_plus: "На грани невозможного",
  impossible: "Невозможно",
};

// Mirrors modules/board_games/chess_adapter.py's _DIFFICULTY_ELO — shown only
// for chess since checkers' engine strength is search-depth based, not ELO.
const DIFFICULTY_CHESS_ELO: Record<BoardGameDifficulty, number> = {
  very_easy: 1320,
  easy: 1500,
  easy_plus: 1650,
  medium: 1800,
  medium_plus: 2000,
  hard: 2200,
  hard_plus: 2450,
  very_hard: 2700,
  very_hard_plus: 2950,
  impossible: 3190,
};

const CHESS_FILES = "abcdefgh";

// Mirrors the exact pixel layout python-chess's chess.svg.board() and the
// draughts.svg.board() renderer use server-side (margin/square-size
// constants read straight from their source, see chess.svg.SQUARE_SIZE=45,
// margin=15 when coordinates=True; draughts.svg.SQUARE_SIZE=45, MARGIN=20)
// — this is what makes a click on the rendered image resolve to the right
// square without needing the server to ship pixel coordinates itself.
function squareFromClick(kind: BoardGameKind, svg: SVGSVGElement, clientX: number, clientY: number): string | null {
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0) {
    return null;
  }
  const viewBox = kind === "chess" ? 390 : 400;
  const margin = kind === "chess" ? 15 : 20;
  const squareSize = 45;
  const scale = rect.width / viewBox;
  const x = (clientX - rect.left) / scale;
  const y = (clientY - rect.top) / scale;
  if (x < margin || y < margin || x >= margin + 8 * squareSize || y >= margin + 8 * squareSize) {
    return null;
  }
  const colGrid = Math.floor((x - margin) / squareSize);
  const rowGrid = Math.floor((y - margin) / squareSize);

  if (kind === "chess") {
    return `${CHESS_FILES[colGrid]}${8 - rowGrid}`;
  }

  // Only the dark squares are playable — even rows have them at odd
  // columns and vice versa (see draughts.svg._get_square_center).
  const evenRow = rowGrid % 2 === 0;
  const isDark = evenRow ? colGrid % 2 === 1 : colGrid % 2 === 0;
  if (!isDark) {
    return null;
  }
  const colInRow = evenRow ? (colGrid - 1) / 2 : colGrid / 2;
  return String(rowGrid * 4 + colInRow + 1);
}

type SquareRect = { leftPct: number; topPct: number; sizePct: number };

// Inverse of squareFromClick — used to position the highlight overlay over
// a named square instead of resolving a click into one.
function squareRect(kind: BoardGameKind, square: string): SquareRect | null {
  const viewBox = kind === "chess" ? 390 : 400;
  const margin = kind === "chess" ? 15 : 20;
  const squareSize = 45;
  let col: number;
  let row: number;
  if (kind === "chess") {
    const fileIndex = CHESS_FILES.indexOf(square[0] ?? "");
    const rankNumber = Number(square.slice(1));
    if (fileIndex < 0 || Number.isNaN(rankNumber)) {
      return null;
    }
    col = fileIndex;
    row = 8 - rankNumber;
  } else {
    const idx = Number(square) - 1;
    if (Number.isNaN(idx) || idx < 0) {
      return null;
    }
    row = Math.floor(idx / 4);
    const colInRow = idx % 4;
    col = row % 2 === 0 ? colInRow * 2 + 1 : colInRow * 2;
  }
  return {
    leftPct: ((margin + col * squareSize) / viewBox) * 100,
    topPct: ((margin + row * squareSize) / viewBox) * 100,
    sizePct: (squareSize / viewBox) * 100,
  };
}

const CHESS_LIGHT_SQUARE = "#ffce9e";
const CHESS_DARK_SQUARE = "#d18b47";
const CHECKERS_DARK_SQUARE = "#b58863"; // pieces only ever sit on dark squares

// Matches the exact default palette chess.svg/draughts.svg render with
// (chess.svg.DEFAULT_COLORS / draughts.svg.DEFAULT_COLORS) — used to mask a
// square with a patch indistinguishable from the real board underneath it.
function squareColor(kind: BoardGameKind, square: string): string {
  if (kind === "checkers") {
    return CHECKERS_DARK_SQUARE;
  }
  const fileIndex = CHESS_FILES.indexOf(square[0] ?? "");
  const rankNumber = Number(square.slice(1));
  if (fileIndex < 0 || Number.isNaN(rankNumber)) {
    return CHESS_LIGHT_SQUARE;
  }
  const row = 8 - rankNumber;
  return (fileIndex + row) % 2 === 1 ? CHESS_DARK_SQUARE : CHESS_LIGHT_SQUARE;
}

const CHESS_PIECE_GLYPH: Record<string, { white: string; black: string }> = {
  K: { white: "♔", black: "♚" },
  Q: { white: "♕", black: "♛" },
  R: { white: "♖", black: "♜" },
  B: { white: "♗", black: "♝" },
  N: { white: "♘", black: "♞" },
  P: { white: "♙", black: "♟" },
};

// SAN doesn't spell out the moving piece's type explicitly for pawns, and
// castling ("O-O"/"O-O-O") doesn't look like a normal move at all — both
// handled here so the sliding token shows the right silhouette.
function chessPieceGlyph(notation: string, color: "white" | "black"): string {
  const first = notation[0];
  const type = first === "O" ? "K" : "KQRBN".includes(first) ? first : "P";
  return CHESS_PIECE_GLYPH[type][color];
}

// Russian draughts notation spells out every square a piece passes
// through on a multi-hop capture ("23x14x5") — chess SAN never has more
// than one square in it (the destination), so this only ever returns more
// than the two click-known endpoints for checkers.
function waypointsForMove(kind: BoardGameKind, notation: string, fromSquare: string, toSquare: string): string[] {
  if (kind === "checkers") {
    const nums = notation.match(/\d+/g);
    if (nums && nums.length >= 2) {
      return nums;
    }
  }
  return [fromSquare, toSquare];
}

interface SlideToken {
  id: number;
  legIndex: number;
  color: "white" | "black";
  glyph: string | null;
  capture: boolean;
  fromSquare: string;
  toSquare: string;
  fromRect: SquareRect;
  toRect: SquareRect;
  durationMs: number;
  arrived: boolean;
}

function resultClass(result: string | null): string {
  if (result === "1-0") {
    return "board-games-panel__result--win";
  }
  if (result === "0-1") {
    return "board-games-panel__result--lose";
  }
  return "board-games-panel__result--draw";
}

function resultText(result: string | null): string {
  // Matches modules/board_games/announce.py's result_text — the player
  // always moves first (no side/color choice), so "1-0" always means the
  // player won and "0-1" always means the engine won, for both games.
  if (!result) {
    return "";
  }
  if (result === "1-0") {
    return "Вы выиграли!";
  }
  if (result === "0-1") {
    return "Победа за движком.";
  }
  return "Ничья.";
}

export function BoardGamesPanel(): JSX.Element {
  // Solitaire/Minesweeper are self-contained client-side minigames (no
  // server session, unlike chess/checkers) — separate flags rather than
  // folding them into `state`/`BoardGameKind` keep this component's
  // existing server-driven chess/checkers flow completely untouched.
  const [solitaireOpen, setSolitaireOpen] = useState(false);
  const [minesweeperOpen, setMinesweeperOpen] = useState(false);
  const [state, setState] = useState<BoardGameState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [starting, setStarting] = useState<BoardGameKind | null>(null);
  const [movePending, setMovePending] = useState(false);
  const [error, setError] = useState("");
  const [selectedDifficulty, setSelectedDifficulty] = useState<BoardGameDifficulty>("medium");
  // "Click a piece on the board, then click its destination square" —
  // selectedOrigin is the square whose legal destinations are currently
  // highlighted; null means no piece is selected yet.
  const [selectedOrigin, setSelectedOrigin] = useState<string | null>(null);
  // Bumped on every start/move so the board wrapper can be re-keyed —
  // remounting it is what makes the CSS "pop" entrance animation replay
  // each time a move lands, instead of only playing once on first mount.
  const [moveSeq, setMoveSeq] = useState(0);
  // A square the player just clicked that wasn't a legal origin/destination
  // — flashed red briefly instead of silently doing nothing, so a missed
  // click reads as "try again", not "is this even working".
  const [invalidSquare, setInvalidSquare] = useState<string | null>(null);
  const invalidFlashTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Actual sliding piece animations — the player's own click always gets
  // one (origin/destination known locally, no need to wait on the
  // server), and so does the engine's reply, using the exact from/to
  // squares BoardGameStateResponse now reports for it (see
  // modules.board_games.domain.EngineMove).
  const [slideTokens, setSlideTokens] = useState<SlideToken[]>([]);
  const nextTokenId = useRef(0);
  const pendingTimeouts = useRef<ReturnType<typeof setTimeout>[]>([]);
  // Tokens for the player's own move are "held" — board_svg won't reflect
  // the move until the server responds (which can lag well past the
  // animation itself, especially with the engine's own "thinking" delay),
  // so the token has to keep sitting at the destination, not vanish on a
  // fixed timer, until clearHeldTokens() runs right as the real state
  // lands. The engine's own token isn't held — board_svg is already
  // correct by the time it starts, so it can just clear itself.
  const heldTokenIds = useRef<Set<number>>(new Set());

  function flashInvalid(square: string): void {
    if (invalidFlashTimeout.current) {
      clearTimeout(invalidFlashTimeout.current);
    }
    setInvalidSquare(square);
    invalidFlashTimeout.current = setTimeout(() => setInvalidSquare(null), 450);
  }

  function clearHeldTokens(): void {
    if (heldTokenIds.current.size === 0) {
      return;
    }
    const ids = heldTokenIds.current;
    setSlideTokens((prev) => prev.filter((t) => !ids.has(t.id)));
    heldTokenIds.current = new Set();
  }

  function legDuration(from: SquareRect, to: SquareRect): number {
    const distance = Math.hypot(to.leftPct - from.leftPct, to.topPct - from.topPct);
    // A one-square step and a full-board queen move shouldn't take the
    // same time to land, or the long one reads as a teleport rather than
    // a slide — scaled by on-screen distance, clamped to a sane range.
    return Math.min(420, Math.max(190, 200 + distance * 2.4));
  }

  // `hold` (see heldTokenIds above): the player's own move keeps its token
  // alive until clearHeldTokens() runs; the engine's clears itself once
  // its animation (all legs, for a checkers multi-hop capture) finishes.
  function animateMove(
    kind: BoardGameKind,
    squares: string[],
    color: "white" | "black",
    glyph: string | null,
    capture: boolean,
    hold: boolean,
    startDelayMs: number,
  ): void {
    const rects = squares.map((sq) => squareRect(kind, sq));
    if (rects.length < 2 || rects.some((r) => r === null)) {
      return;
    }
    const validRects = rects as SquareRect[];
    const id = nextTokenId.current++;
    if (hold) {
      heldTokenIds.current.add(id);
    }

    function runLeg(legIndex: number): void {
      const fromRect = validRects[legIndex];
      const toRect = validRects[legIndex + 1];
      const durationMs = legDuration(fromRect, toRect);
      setSlideTokens((prev) => [
        ...prev.filter((t) => t.id !== id),
        {
          id,
          legIndex,
          color,
          glyph,
          capture,
          fromSquare: squares[legIndex],
          toSquare: squares[legIndex + 1],
          fromRect,
          toRect,
          durationMs,
          arrived: false,
        },
      ]);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setSlideTokens((prev) => prev.map((t) => (t.id === id ? { ...t, arrived: true } : t)));
        });
      });
      const isLastLeg = legIndex + 2 >= validRects.length;
      const advanceTimeout = setTimeout(
        () => {
          if (!isLastLeg) {
            runLeg(legIndex + 1);
          } else if (!hold) {
            setSlideTokens((prev) => prev.filter((t) => t.id !== id));
          }
        },
        durationMs + (isLastLeg ? 60 : 90),
      );
      pendingTimeouts.current.push(advanceTimeout);
    }

    const startTimeout = setTimeout(() => runLeg(0), startDelayMs);
    pendingTimeouts.current.push(startTimeout);
  }

  useEffect(() => {
    return () => {
      if (invalidFlashTimeout.current) {
        clearTimeout(invalidFlashTimeout.current);
      }
      pendingTimeouts.current.forEach(clearTimeout);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getCurrentBoardGame()
      .then((current) => {
        if (!cancelled) {
          setState(current);
          setLoaded(true);
        }
      })
      .catch((err) => {
        console.error("Failed to load the current board game:", err);
        if (!cancelled) {
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleStart(kind: BoardGameKind): Promise<void> {
    setStarting(kind);
    setError("");
    setSelectedOrigin(null);
    try {
      setState(await startBoardGame(kind, selectedDifficulty));
      setMoveSeq((n) => n + 1);
    } catch (err) {
      console.error(`Failed to start a ${kind} game:`, err);
      setError("Не удалось начать игру.");
    } finally {
      setStarting(null);
    }
  }

  async function handleMove(notation: string, fromSquare: string, toSquare: string): Promise<void> {
    if (!state) {
      return;
    }
    const kind = state.kind;
    setMovePending(true);
    setError("");
    setSelectedOrigin(null);
    // Starts immediately, independent of the network round-trip — the
    // player should see their own piece move right away, not after
    // waiting for the server (and the engine's own ~0.6s+ "thinking"
    // delay) to respond. Held until the response actually lands (see
    // clearHeldTokens) since board_svg won't reflect this move until then.
    const playerSquares = waypointsForMove(kind, notation, fromSquare, toSquare);
    const playerGlyph = kind === "chess" ? chessPieceGlyph(notation, "white") : null;
    animateMove(kind, playerSquares, "white", playerGlyph, notation.includes("x"), true, 0);
    try {
      const newState = await playBoardGameMove(notation);
      clearHeldTokens();
      setState(newState);
      setMoveSeq((n) => n + 1);
      if (newState.last_engine_move && newState.last_engine_move_from && newState.last_engine_move_to) {
        const engineSquares = waypointsForMove(
          kind,
          newState.last_engine_move,
          newState.last_engine_move_from,
          newState.last_engine_move_to,
        );
        const engineGlyph = kind === "chess" ? chessPieceGlyph(newState.last_engine_move, "black") : null;
        animateMove(kind, engineSquares, "black", engineGlyph, newState.last_engine_move.includes("x"), false, 120);
      }
    } catch (err) {
      console.error("Failed to play a board game move:", err);
      setError("Не удалось сделать ход.");
      clearHeldTokens();
    } finally {
      setMovePending(false);
    }
  }

  function handleBoardClick(event: MouseEvent<HTMLDivElement>): void {
    if (!state || movePending || state.is_over) {
      return;
    }
    const svg = event.currentTarget.querySelector("svg");
    if (!svg) {
      return;
    }
    const square = squareFromClick(state.kind, svg, event.clientX, event.clientY);
    if (!square) {
      return;
    }
    const hasOwnMoves = state.legal_move_squares.some((m) => m.from_square === square);

    if (selectedOrigin === null) {
      if (hasOwnMoves) {
        setSelectedOrigin(square);
      } else {
        flashInvalid(square);
      }
      return;
    }

    if (square === selectedOrigin) {
      setSelectedOrigin(null);
      return;
    }

    const match = state.legal_move_squares.find((m) => m.from_square === selectedOrigin && m.to_square === square);
    if (match) {
      void handleMove(match.label, match.from_square, match.to_square);
      return;
    }

    if (hasOwnMoves) {
      // Clicked a different piece instead of a destination — switch selection.
      setSelectedOrigin(square);
    } else {
      flashInvalid(square);
    }
  }

  async function handleFinish(): Promise<void> {
    setMovePending(true);
    setError("");
    try {
      await finishBoardGame();
      setState(null);
    } catch (err) {
      console.error("Failed to finish the board game:", err);
      setError("Не удалось завершить игру.");
    } finally {
      setMovePending(false);
    }
  }

  if (!loaded) {
    return (
      <div className="board-games-panel">
        <p className="status-detail">Загрузка…</p>
      </div>
    );
  }

  if (solitaireOpen) {
    return (
      <div className="board-games-panel">
        <SolitaireGame />
        <button type="button" className="board-games-panel__back" onClick={() => setSolitaireOpen(false)}>
          ← Выбрать другую игру
        </button>
      </div>
    );
  }

  if (minesweeperOpen) {
    return (
      <div className="board-games-panel">
        <MinesweeperGame />
        <button type="button" className="board-games-panel__back" onClick={() => setMinesweeperOpen(false)}>
          ← Выбрать другую игру
        </button>
      </div>
    );
  }

  return (
    <div className="board-games-panel">
      {error && <p className="status-error">{error}</p>}

      {!state ? (
        <>
          <p className="status-detail">Сыграйте в шахматы или шашки против движка — голосом или здесь, ходы кликом.</p>

          {/* No ELO number here — which game this applies to isn't chosen
              yet (the same slider sets difficulty for either "Начать
              шахматы" or "Начать шашки" below), and ELO is a chess-only
              concept (checkers' engine strength is search-depth based, see
              DIFFICULTY_CHESS_ELO's own docstring) — showing a chess ELO
              number before the player has even picked chess was
              misleading. The ELO estimate still appears once a chess game
              is actually running, in the in-game status line below. */}
          <span className="board-games-panel__label">Сложность: {DIFFICULTY_LABEL[selectedDifficulty]}</span>
          <input
            type="range"
            className="board-games-panel__difficulty-slider"
            min={0}
            max={DIFFICULTY_OPTIONS.length - 1}
            step={1}
            value={DIFFICULTY_OPTIONS.indexOf(selectedDifficulty)}
            style={{
              ["--range-fill" as string]: `${(DIFFICULTY_OPTIONS.indexOf(selectedDifficulty) / (DIFFICULTY_OPTIONS.length - 1)) * 100}%`,
            }}
            onChange={(event) => setSelectedDifficulty(DIFFICULTY_OPTIONS[Number(event.target.value)])}
            disabled={starting !== null}
          />
          <p className="status-detail">
            Шахматы: сила движка растёт с уровнем (ELO). Шашки: растёт глубина поиска движка.
          </p>

          <div className="board-games-panel__start-row">
            {(["chess", "checkers"] as const).map((kind) => {
              const Icon = KIND_ICON[kind];
              return (
                <button
                  key={kind}
                  type="button"
                  className="board-games-panel__start-tile"
                  onClick={() => void handleStart(kind)}
                  disabled={starting !== null}
                >
                  <Icon size={26} />
                  <span>{starting === kind ? "…" : KIND_LABEL[kind]}</span>
                </button>
              );
            })}
            <button
              type="button"
              className="board-games-panel__start-tile board-games-panel__start-tile--solitaire"
              onClick={() => setSolitaireOpen(true)}
              disabled={starting !== null}
            >
              <SolitaireIcon size={26} />
              <span>Пасьянс</span>
            </button>
            <button
              type="button"
              className="board-games-panel__start-tile board-games-panel__start-tile--minesweeper"
              onClick={() => setMinesweeperOpen(true)}
              disabled={starting !== null}
            >
              <Bomb size={26} />
              <span>Сапёр</span>
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="board-games-panel__board">
            <div className="board-games-panel__board-frame" onClick={handleBoardClick}>
              <div
                key={moveSeq}
                className="board-games-panel__board-svg"
                dangerouslySetInnerHTML={{ __html: state.board_svg }}
              />
              <div className="board-games-panel__board-overlay">
                {slideTokens.map((token) => {
                  const rect = token.arrived ? token.toRect : token.fromRect;
                  const modeClass = token.glyph
                    ? "board-games-panel__slide-token--glyph"
                    : "board-games-panel__slide-token--disc";
                  return (
                    <Fragment key={`${token.id}-${token.legIndex}`}>
                      <div
                        className="board-games-panel__square-mask"
                        style={{
                          left: `${token.fromRect.leftPct}%`,
                          top: `${token.fromRect.topPct}%`,
                          width: `${token.fromRect.sizePct}%`,
                          height: `${token.fromRect.sizePct}%`,
                          background: squareColor(state.kind, token.fromSquare),
                        }}
                      />
                      {!token.arrived && (
                        <div
                          className="board-games-panel__square-mask"
                          style={{
                            left: `${token.toRect.leftPct}%`,
                            top: `${token.toRect.topPct}%`,
                            width: `${token.toRect.sizePct}%`,
                            height: `${token.toRect.sizePct}%`,
                            background: squareColor(state.kind, token.toSquare),
                          }}
                        />
                      )}
                      <div
                        className={`board-games-panel__slide-token board-games-panel__slide-token--${token.color} ${modeClass}`}
                        style={{
                          left: `${rect.leftPct}%`,
                          top: `${rect.topPct}%`,
                          width: `${rect.sizePct}%`,
                          height: `${rect.sizePct}%`,
                          transitionDuration: `${token.durationMs}ms`,
                        }}
                      >
                        {token.glyph && (
                          <span className="board-games-panel__slide-token-glyph">{token.glyph}</span>
                        )}
                      </div>
                      {token.capture && token.arrived && (
                        <div
                          className="board-games-panel__capture-burst"
                          style={{
                            left: `${token.toRect.leftPct}%`,
                            top: `${token.toRect.topPct}%`,
                            width: `${token.toRect.sizePct}%`,
                            height: `${token.toRect.sizePct}%`,
                          }}
                        />
                      )}
                    </Fragment>
                  );
                })}
                {invalidSquare &&
                  (() => {
                    const rect = squareRect(state.kind, invalidSquare);
                    return rect ? (
                      <div
                        className="board-games-panel__square-highlight board-games-panel__square-highlight--invalid"
                        style={{
                          left: `${rect.leftPct}%`,
                          top: `${rect.topPct}%`,
                          width: `${rect.sizePct}%`,
                          height: `${rect.sizePct}%`,
                        }}
                      />
                    ) : null;
                  })()}
                {selectedOrigin &&
                  (() => {
                    const rect = squareRect(state.kind, selectedOrigin);
                    return rect ? (
                      <div
                        className="board-games-panel__square-highlight board-games-panel__square-highlight--origin"
                        style={{
                          left: `${rect.leftPct}%`,
                          top: `${rect.topPct}%`,
                          width: `${rect.sizePct}%`,
                          height: `${rect.sizePct}%`,
                        }}
                      />
                    ) : null;
                  })()}
                {selectedOrigin &&
                  state.legal_move_squares
                    .filter((m) => m.from_square === selectedOrigin)
                    .map((m) => {
                      const rect = squareRect(state.kind, m.to_square);
                      if (!rect) {
                        return null;
                      }
                      return (
                        <div
                          key={m.label}
                          className="board-games-panel__square-highlight board-games-panel__square-highlight--target"
                          style={{
                            left: `${rect.leftPct}%`,
                            top: `${rect.topPct}%`,
                            width: `${rect.sizePct}%`,
                            height: `${rect.sizePct}%`,
                          }}
                        />
                      );
                    })}
              </div>
            </div>
          </div>

          <p className="status-detail">
            {KIND_LABEL[state.kind]}
            {state.difficulty && ` · сложность: ${DIFFICULTY_LABEL[state.difficulty]}`}
            {state.difficulty && state.kind === "chess" && ` (≈${DIFFICULTY_CHESS_ELO[state.difficulty]} ELO)`}
            {state.last_player_move && ` · вы: ${state.last_player_move}`}
            {state.last_engine_move && ` · движок: ${state.last_engine_move}`}
          </p>
          {state.is_check && !state.is_over && <p className="status-error">Шах!</p>}
          {state.mistake_message && <p className="board-games-panel__mistake">{state.mistake_message}</p>}

          {state.is_over ? (
            <>
              <p className={`board-games-panel__result ${resultClass(state.result)}`}>{resultText(state.result)}</p>
              <div className="board-games-panel__start-row">
                <button type="button" onClick={() => void handleStart(state.kind)} disabled={starting !== null}>
                  Играть ещё раз
                </button>
                <button type="button" onClick={() => setState(null)}>
                  Выбрать игру
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="board-games-panel__hint">
                {selectedOrigin === null
                  ? "Нажмите на свою фигуру на доске."
                  : `Фигура ${selectedOrigin} — нажмите на подсвеченное поле или на неё саму, чтобы отменить.`}
              </p>
              <button
                type="button"
                className="board-games-panel__finish"
                onClick={() => void handleFinish()}
                disabled={movePending}
              >
                Сдаться
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
