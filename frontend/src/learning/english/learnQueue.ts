import type { Direction, EnglishCard, LearnMode, LearnSettings } from "../../api/english";

const MASK = "_____";

export type Stage = "choice" | "input";

export interface QueueItem {
  cardId: number;
  stage: Stage;
}

export interface LearnState {
  queue: QueueItem[];
  learned: number[];
  points: number;
  totalPoints: number;
}

const OPTION_COUNT = 4;

function stagesFor(mode: LearnMode): Stage[] {
  if (mode === "choice") {
    return ["choice"];
  }
  if (mode === "input") {
    return ["input"];
  }
  return ["choice", "input"];
}

export function shuffled<T>(items: readonly T[], random: () => number = Math.random): T[] {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    const current = copy[index] as T;
    copy[index] = copy[target] as T;
    copy[target] = current;
  }
  return copy;
}

export function initialState(cards: readonly EnglishCard[], settings: LearnSettings, random: () => number = Math.random): LearnState {
  const ordered = settings.shuffle ? shuffled(cards, random) : [...cards];
  const firstStage = stagesFor(settings.mode)[0] ?? "input";
  return {
    queue: ordered.map((card) => ({ cardId: card.id, stage: firstStage })),
    learned: [],
    points: 0,
    totalPoints: cards.length * stagesFor(settings.mode).length,
  };
}

export function applyAnswer(state: LearnState, correct: boolean, mode: LearnMode): LearnState {
  const [current, ...rest] = state.queue;
  if (!current) {
    return state;
  }
  if (!correct) {
    return { ...state, queue: [...rest, current] };
  }
  const stages = stagesFor(mode);
  const nextStage = stages[stages.indexOf(current.stage) + 1];
  if (nextStage) {
    const insertAt = Math.min(rest.length, 2);
    return {
      ...state,
      queue: [...rest.slice(0, insertAt), { cardId: current.cardId, stage: nextStage }, ...rest.slice(insertAt)],
      points: state.points + 1,
    };
  }
  return { ...state, queue: rest, learned: [...state.learned, current.cardId], points: state.points + 1 };
}

export function promptText(card: EnglishCard, direction: Direction): string {
  return direction === "en_ru" ? card.word : card.translations_ru.join(", ");
}

export function answerText(card: EnglishCard, direction: Direction): string {
  return direction === "en_ru" ? (card.translations_ru[0] ?? card.word) : card.word;
}

export function buildOptions(
  card: EnglishCard,
  cards: readonly EnglishCard[],
  direction: Direction,
  random: () => number = Math.random,
): string[] {
  const correct = answerText(card, direction);
  const others = cards.filter((item) => item.id !== card.id);
  const samePos = shuffled(
    others.filter((item) => item.pos === card.pos),
    random,
  );
  const rest = shuffled(
    others.filter((item) => item.pos !== card.pos),
    random,
  );
  const options = [correct];
  for (const candidate of [...samePos, ...rest]) {
    const text = answerText(candidate, direction);
    if (!options.some((option) => option.toLowerCase() === text.toLowerCase())) {
      options.push(text);
    }
    if (options.length === OPTION_COUNT) {
      break;
    }
  }
  return shuffled(options, random);
}

export function showsContext(card: EnglishCard, settings: LearnSettings): boolean {
  return card.kind === "word" ? settings.contextForWords : settings.contextForExpressions;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function contextLine(card: EnglishCard, direction: Direction): string {
  if (direction === "en_ru") {
    return card.example;
  }
  const targets = [card.surface_form, card.word].filter((item): item is string => Boolean(item && item.trim()));
  let masked = card.example;
  for (const target of targets) {
    masked = masked.replace(new RegExp(escapeRegExp(target), "gi"), MASK);
  }
  return masked;
}
