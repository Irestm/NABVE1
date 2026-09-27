import type { EnglishCard, ItemKind, LevelFilter, StoredLevel } from "../../api/english";

export const STORED_LEVELS: StoredLevel[] = ["A1", "A2", "B1", "B2"];
export const DEFAULT_FILTER: LevelFilter = { levels: ["A2", "B1", "B2"], include_unleveled: false, mwe_mode: "always" };

export const KIND_LABELS: Record<ItemKind, string> = {
  word: "слово",
  phrasal_verb: "фразовый глагол",
  idiom: "идиома",
  collocation: "коллокация",
  slang: "сленг",
};

export const ITEM_KINDS: ItemKind[] = ["word", "phrasal_verb", "idiom", "collocation", "slang"];

export function isFilterEmpty(filter: LevelFilter): boolean {
  return filter.levels.length === 0 && !filter.include_unleveled;
}

export function admits(card: Pick<EnglishCard, "kind" | "cefr">, filter: LevelFilter): boolean {
  if (isFilterEmpty(filter)) {
    return false;
  }
  if (card.kind !== "word" && filter.mwe_mode === "always") {
    return true;
  }
  if (card.cefr === null) {
    return filter.include_unleveled;
  }
  return (filter.levels as string[]).includes(card.cefr);
}

export function applyFilter<T extends Pick<EnglishCard, "kind" | "cefr">>(cards: readonly T[], filter: LevelFilter): T[] {
  return cards.filter((card) => admits(card, filter));
}

export function filterSummary(filter: LevelFilter): string {
  if (isFilterEmpty(filter)) {
    return "уровни не выбраны";
  }
  const parts: string[] = STORED_LEVELS.filter((level) => filter.levels.includes(level));
  if (filter.include_unleveled) {
    parts.push("без уровня");
  }
  const mwe = filter.mwe_mode === "always" ? "выражения — все" : "выражения — по уровням";
  return `${parts.join(" · ")} · ${mwe}`;
}

export function sensesByLemma(cards: readonly EnglishCard[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const card of cards) {
    counts.set(card.lemma, (counts.get(card.lemma) ?? 0) + 1);
  }
  return counts;
}
