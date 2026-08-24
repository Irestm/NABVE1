import { useEffect, useState } from "react";
// Reuses the shared "nostalgic desktop window" chrome classes (titlebar,
// dots, win overlay) instead of duplicating that CSS — same shared/
// reusable-component convention as the rest of this codebase.
import "./GameWindowChrome.css";
import "./SolitaireGame.css";

// Original Klondike implementation — standard 52-card deal-3 rules are not
// copyrightable, no code/art borrowed from any existing solitaire build.
// Card faces are plain typographic rank text + Unicode suit glyphs
// (♠♥♦♣), not artwork.

type Suit = "spades" | "hearts" | "diamonds" | "clubs";

interface CardT {
  id: string;
  suit: Suit;
  rank: number;
  faceUp: boolean;
}

const SUIT_META: Record<Suit, { symbol: string; color: "red" | "black" }> = {
  spades: { symbol: "♠", color: "black" },
  hearts: { symbol: "♥", color: "red" },
  diamonds: { symbol: "♦", color: "red" },
  clubs: { symbol: "♣", color: "black" },
};

const SUIT_ORDER: Suit[] = ["spades", "hearts", "diamonds", "clubs"];

const RANK_LABEL: Record<number, string> = {
  1: "A",
  11: "J",
  12: "Q",
  13: "K",
};

function rankLabel(rank: number): string {
  return RANK_LABEL[rank] ?? String(rank);
}

function colorOf(suit: Suit): "red" | "black" {
  return SUIT_META[suit].color;
}

function shuffledDeck(): CardT[] {
  const deck: CardT[] = [];
  for (const suit of SUIT_ORDER) {
    for (let rank = 1; rank <= 13; rank++) {
      deck.push({ id: `${suit}-${rank}`, suit, rank, faceUp: false });
    }
  }
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

function deal(): { stock: CardT[]; tableau: CardT[][] } {
  const deck = shuffledDeck();
  const tableau: CardT[][] = [[], [], [], [], [], [], []];
  let idx = 0;
  for (let col = 0; col < 7; col++) {
    for (let row = 0; row <= col; row++) {
      const card = deck[idx++];
      tableau[col].push({ ...card, faceUp: row === col });
    }
  }
  const stock = deck.slice(idx).map((c) => ({ ...c, faceUp: false }));
  return { stock, tableau };
}

type Selection = { zone: "tableau"; col: number; index: number } | { zone: "waste" } | { zone: "foundation"; suit: Suit } | null;

type Destination = { type: "tableau"; col: number } | { type: "foundation"; suit: Suit };

function CardFace({ card, selected }: { card: CardT; selected?: boolean }): JSX.Element {
  if (!card.faceUp) {
    return <div className="solitaire-card solitaire-card--back" />;
  }
  const meta = SUIT_META[card.suit];
  return (
    <div
      className={`solitaire-card solitaire-card--face solitaire-card--${meta.color}${
        selected ? " solitaire-card--selected" : ""
      }`}
    >
      <span className="solitaire-card__corner solitaire-card__corner--top">
        {rankLabel(card.rank)}
        {meta.symbol}
      </span>
      <span className="solitaire-card__pip">{meta.symbol}</span>
      <span className="solitaire-card__corner solitaire-card__corner--bottom">
        {rankLabel(card.rank)}
        {meta.symbol}
      </span>
    </div>
  );
}

export function SolitaireGame(): JSX.Element {
  const [{ stock: initialStock, tableau: initialTableau }] = useState(() => deal());
  const [stock, setStock] = useState<CardT[]>(initialStock);
  const [waste, setWaste] = useState<CardT[]>([]);
  const [tableau, setTableau] = useState<CardT[][]>(initialTableau);
  const [foundations, setFoundations] = useState<Record<Suit, CardT[]>>({
    spades: [],
    hearts: [],
    diamonds: [],
    clubs: [],
  });
  const [selection, setSelection] = useState<Selection>(null);
  const [moves, setMoves] = useState(0);
  const [won, setWon] = useState(false);

  useEffect(() => {
    const total = SUIT_ORDER.reduce((sum, suit) => sum + foundations[suit].length, 0);
    if (total === 52) setWon(true);
  }, [foundations]);

  function newGame() {
    const fresh = deal();
    setStock(fresh.stock);
    setTableau(fresh.tableau);
    setWaste([]);
    setFoundations({ spades: [], hearts: [], diamonds: [], clubs: [] });
    setSelection(null);
    setMoves(0);
    setWon(false);
  }

  function getMovingCards(sel: NonNullable<Selection>): CardT[] {
    if (sel.zone === "tableau") return tableau[sel.col].slice(sel.index);
    if (sel.zone === "waste") return waste.length ? [waste[waste.length - 1]] : [];
    const pile = foundations[sel.suit];
    return pile.length ? [pile[pile.length - 1]] : [];
  }

  function validateMove(moving: CardT[], dest: Destination): boolean {
    if (moving.length === 0) return false;
    const bottom = moving[0];
    if (dest.type === "tableau") {
      const col = tableau[dest.col];
      if (col.length === 0) return bottom.rank === 13;
      const top = col[col.length - 1];
      return top.faceUp && top.rank === bottom.rank + 1 && colorOf(top.suit) !== colorOf(bottom.suit);
    }
    if (moving.length !== 1) return false;
    const pile = foundations[dest.suit];
    return bottom.suit === dest.suit && bottom.rank === pile.length + 1;
  }

  function removeFromSource(sel: NonNullable<Selection>) {
    if (sel.zone === "tableau") {
      setTableau((prev) => {
        const next = prev.slice();
        const newCol = prev[sel.col].slice(0, sel.index);
        if (newCol.length > 0) {
          newCol[newCol.length - 1] = { ...newCol[newCol.length - 1], faceUp: true };
        }
        next[sel.col] = newCol;
        return next;
      });
    } else if (sel.zone === "waste") {
      setWaste((prev) => prev.slice(0, -1));
    } else {
      setFoundations((prev) => ({ ...prev, [sel.suit]: prev[sel.suit].slice(0, -1) }));
    }
  }

  function appendToDestination(dest: Destination, moving: CardT[]) {
    if (dest.type === "tableau") {
      setTableau((prev) => {
        const next = prev.slice();
        next[dest.col] = [...next[dest.col], ...moving];
        return next;
      });
    } else {
      setFoundations((prev) => ({ ...prev, [dest.suit]: [...prev[dest.suit], ...moving] }));
    }
  }

  function attemptMove(sel: Selection, dest: Destination) {
    if (!sel) return;
    const moving = getMovingCards(sel);
    if (!validateMove(moving, dest)) {
      setSelection(null);
      return;
    }
    removeFromSource(sel);
    appendToDestination(dest, moving);
    setSelection(null);
    setMoves((m) => m + 1);
  }

  function onStockClick() {
    setSelection(null);
    if (stock.length > 0) {
      const card = stock[stock.length - 1];
      setStock((prev) => prev.slice(0, -1));
      setWaste((prev) => [...prev, { ...card, faceUp: true }]);
    } else if (waste.length > 0) {
      setStock([...waste].reverse().map((c) => ({ ...c, faceUp: false })));
      setWaste([]);
    }
  }

  function onWasteClick() {
    if (waste.length === 0) return;
    if (selection?.zone === "waste") {
      setSelection(null);
      return;
    }
    setSelection({ zone: "waste" });
  }

  function onFoundationClick(suit: Suit) {
    if (selection?.zone === "foundation" && selection.suit === suit) {
      setSelection(null);
      return;
    }
    if (selection) {
      attemptMove(selection, { type: "foundation", suit });
      return;
    }
    if (foundations[suit].length > 0) setSelection({ zone: "foundation", suit });
  }

  function onCardClick(col: number, index: number, card: CardT) {
    if (selection) {
      if (selection.zone === "tableau" && selection.col === col && selection.index === index) {
        setSelection(null);
        return;
      }
      attemptMove(selection, { type: "tableau", col });
      return;
    }
    if (!card.faceUp) return;
    setSelection({ zone: "tableau", col, index });
  }

  function onColumnBackgroundClick(col: number) {
    if (!selection) return;
    attemptMove(selection, { type: "tableau", col });
  }

  function isSelected(col: number, index: number): boolean {
    return selection?.zone === "tableau" && selection.col === col && index >= selection.index;
  }

  return (
    <div className="solitaire-window">
      <div className="game-window__titlebar">
        <span className="game-window__title">Пасьянс «Косынка»</span>
        <div className="game-window__dots">
          <span className="game-window__dot game-window__dot--min" />
          <span className="game-window__dot game-window__dot--max" />
          <span className="game-window__dot game-window__dot--close" />
        </div>
      </div>

      <div className="solitaire-window__toolbar">
        <button type="button" className="solitaire-window__new-btn" onClick={newGame}>
          Новая игра
        </button>
        <span className="solitaire-window__moves">Ходов: {moves}</span>
      </div>

      <div className="solitaire-window__table">
        <div className="solitaire-window__top-row">
          <div className="solitaire-pile" onClick={onStockClick}>
            {stock.length > 0 ? (
              <CardFace card={stock[stock.length - 1]} />
            ) : (
              <div className="solitaire-pile__empty solitaire-pile__empty--recycle">&#8635;</div>
            )}
          </div>
          <div className="solitaire-pile" onClick={onWasteClick}>
            {waste.length > 0 ? (
              <CardFace card={waste[waste.length - 1]} selected={selection?.zone === "waste"} />
            ) : (
              <div className="solitaire-pile__empty" />
            )}
          </div>
          <div className="solitaire-window__spacer" />
          {SUIT_ORDER.map((suit) => {
            const pile = foundations[suit];
            return (
              <div key={suit} className="solitaire-pile" onClick={() => onFoundationClick(suit)}>
                {pile.length > 0 ? (
                  <CardFace card={pile[pile.length - 1]} selected={selection?.zone === "foundation" && selection.suit === suit} />
                ) : (
                  <div className="solitaire-pile__empty">{SUIT_META[suit].symbol}</div>
                )}
              </div>
            );
          })}
        </div>

        <div className="solitaire-window__tableau">
          {tableau.map((col, ci) => (
            <div
              key={ci}
              className="solitaire-column"
              style={{ height: col.length > 0 ? 124 + (col.length - 1) * 36 : undefined }}
              onClick={() => onColumnBackgroundClick(ci)}
            >
              {col.length === 0 && <div className="solitaire-pile__empty solitaire-pile__empty--column" />}
              {col.map((card, idx) => (
                <div
                  key={card.id}
                  className="solitaire-column__slot"
                  style={{ top: idx * 36 }}
                  onClick={(event) => {
                    event.stopPropagation();
                    onCardClick(ci, idx, card);
                  }}
                >
                  <CardFace card={card} selected={isSelected(ci, idx)} />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {won && (
        <div className="game-window__overlay">
          <p className="game-window__overlay-title">Победа!</p>
          <p className="game-window__overlay-score">Ходов: {moves}</p>
          <button type="button" className="solitaire-window__new-btn" onClick={newGame}>
            Новая игра
          </button>
        </div>
      )}
    </div>
  );
}
