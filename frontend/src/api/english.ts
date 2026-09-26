import { requestForm, requestJson } from "./client";

export type Direction = "en_ru" | "ru_en";
export type LearnMode = "choice" | "input" | "mixed";
export type EpisodeSource = "youtube" | "opensubtitles" | "manual" | "ai_guess";

export interface EnglishEpisode {
  id: number;
  series_id: number;
  season: number;
  episode: number;
  code: string;
  title: string | null;
  source: EpisodeSource;
  word_count: number;
  card_count: number;
  display_name: string;
}

export interface EnglishSeries {
  id: number;
  title: string;
  imdb_id: string | null;
  episodes: EnglishEpisode[];
}

export interface EnglishLibrary {
  series: EnglishSeries[];
  cefr_attribution: string;
}

export interface EnglishCard {
  id: number;
  episode_id: number;
  word: string;
  lemma: string;
  pos: string;
  cefr: string | null;
  translations_ru: string[];
  definition_en: string;
  example: string;
  timestamp_ms: number;
  category: "core" | "extra";
}

export interface CardJob {
  id: number;
  episode_id: number;
  state: "running" | "done" | "failed";
  done: number;
  total: number;
  created: number;
  skipped: number;
  error: string | null;
}

export interface ImportedEpisode {
  series: EnglishSeries;
  episode: EnglishEpisode;
  words: unknown[];
  job: CardJob | null;
}

export interface ShowOption {
  tmdb_id: number;
  name: string;
  year: number | null;
}

export interface NeedsInput {
  kind: "details" | "series" | "subtitles";
  message: string;
  guess: {
    series_title: string | null;
    season: number | null;
    episode: number | null;
    is_youtube: boolean;
    page_title: string | null;
  };
  missing: string[];
  options: ShowOption[];
  alternatives: string[];
  problems: string[];
}

export interface LinkImportResult {
  status: "imported" | "needs_input";
  imported: ImportedEpisode | null;
  needs_input: NeedsInput | null;
}

export interface LinkImportRequest {
  url: string;
  series_title?: string;
  season?: number;
  episode?: number;
  tmdb_id?: number;
  allow_ai_guess?: boolean;
}

export interface CredentialsStatus {
  tmdb: boolean;
  opensubtitles_api_key: boolean;
  opensubtitles_account: boolean;
}

export interface CredentialsUpdate {
  tmdb_api_key?: string;
  opensubtitles_api_key?: string;
  opensubtitles_username?: string;
  opensubtitles_password?: string;
}

export interface LearnSettings {
  shuffle: boolean;
  direction: Direction;
  mode: LearnMode;
}

export interface LearnSession {
  id: number;
  episode_id: number;
  settings: LearnSettings;
}

export interface AnswerResult {
  correct: boolean;
  exact: boolean;
  matched: string | null;
  expected: string[];
}

export interface SessionSummary {
  session_id: number;
  mistakes: number;
  hard_words: { card: EnglishCard; mistakes: number }[];
}

export function getLibrary(): Promise<EnglishLibrary> {
  return requestJson<EnglishLibrary>("/api/english/library");
}

export function importFromLink(request: LinkImportRequest): Promise<LinkImportResult> {
  return requestJson<LinkImportResult>("/api/english/import", { method: "POST", body: JSON.stringify(request) });
}

export function importSrt(seriesTitle: string, season: number, episode: number, file: File): Promise<ImportedEpisode> {
  const form = new FormData();
  form.append("series_title", seriesTitle);
  form.append("season", String(season));
  form.append("episode", String(episode));
  form.append("file", file, file.name);
  return requestForm<ImportedEpisode>("/api/english/import/srt", form);
}

export function getEpisodeCards(episodeId: number): Promise<EnglishCard[]> {
  return requestJson<EnglishCard[]>(`/api/english/episodes/${episodeId}/cards`);
}

export function startCardGeneration(episodeId: number): Promise<CardJob> {
  return requestJson<CardJob>(`/api/english/episodes/${episodeId}/cards`, { method: "POST" });
}

export function getJob(jobId: number): Promise<CardJob> {
  return requestJson<CardJob>(`/api/english/jobs/${jobId}`);
}

export async function deleteCard(cardId: number): Promise<void> {
  await requestJson<{ deleted: boolean }>(`/api/english/cards/${cardId}`, { method: "DELETE" });
}

export function getCredentialsStatus(): Promise<CredentialsStatus> {
  return requestJson<CredentialsStatus>("/api/english/credentials");
}

export function updateCredentials(update: CredentialsUpdate): Promise<CredentialsStatus> {
  return requestJson<CredentialsStatus>("/api/english/credentials", { method: "PUT", body: JSON.stringify(update) });
}

export function startSession(episodeId: number, settings: LearnSettings): Promise<LearnSession> {
  return requestJson<LearnSession>(`/api/english/episodes/${episodeId}/sessions`, {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function sendAnswer(
  sessionId: number,
  cardId: number,
  mode: "choice" | "input",
  answer: string,
): Promise<AnswerResult> {
  return requestJson<AnswerResult>(`/api/english/sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify({ card_id: cardId, mode, answer }),
  });
}

export function finishSession(sessionId: number): Promise<SessionSummary> {
  return requestJson<SessionSummary>(`/api/english/sessions/${sessionId}/finish`, { method: "POST" });
}
