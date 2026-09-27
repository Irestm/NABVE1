export function pluralRu(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  const last = count % 10;
  const noun = tail >= 11 && tail <= 14 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many;
  return `${count} ${noun}`;
}

export function wordsLabel(count: number): string {
  return pluralRu(count, "слово", "слова", "слов");
}

export function phrasesLabel(count: number): string {
  return pluralRu(count, "фраза", "фразы", "фраз");
}

export function formatTime(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number): string => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}
