import { requestForm, requestJson } from "./client";

export type Direction = "en_ru" | "ru_en";
export type LearnMode = "choice" | "input" | "mixed";
export type EpisodeSource = "youtube" | "opensubtitles" | "manual" | "ai_guess";

export type CefrLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2";
export type StoredLevel = "A1" | "A2" | "B1" | "B2";
export type ItemKind = "word" | "phrasal_verb" | "idiom" | "collocation" | "slang";
export type TitleKind = "series" | "movie";
export type MweMode = "follow_levels" | "always";

export interface EnglishEpisode {
  id: number;
  title_id: number;
  season: number | null;
  episode: number | null;
  part: number | null;
  start_ms: number | null;
  end_ms: number | null;
  code: string;
  title: string | null;
  source: EpisodeSource;
  word_count: number;
  card_count: number;
  words: number;
  phrases: number;
  display_name: string;
  has_override: boolean;
}

export interface EnglishTitle {
  id: number;
  kind: TitleKind;
  name: string;
  year: number | null;
  imdb_id: string | null;
  display_name: string;
  words: number;
  phrases: number;
  has_override: boolean;
  episodes: EnglishEpisode[];
}

export interface EnglishLibrary {
  titles: EnglishTitle[];
  cefr_attribution: string;
  lexicon_attribution: string;
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
  kind: ItemKind;
  surface_form: string | null;
  sense_label: string | null;
  literal_translation: string | null;
  cefr_source: string | null;
  confidence: number | null;
  archived: boolean;
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
  phase: "expressions" | "cards" | string;
}

export interface ImportedEpisode {
  title: EnglishTitle;
  episode: EnglishEpisode;
  episodes: EnglishEpisode[];
  words: unknown[];
  job: CardJob | null;
}

export interface ShowOption {
  tmdb_id: number;
  name: string;
  year: number | null;
  kind: TitleKind;
  poster_url: string | null;
}

export interface NeedsInput {
  kind: "details" | "series" | "title" | "subtitles";
  message: string;
  guess: {
    series_title: string | null;
    season: number | null;
    episode: number | null;
    is_youtube: boolean;
    page_title: string | null;
    kind: TitleKind | null;
    year: number | null;
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
  kind?: TitleKind;
  year?: number;
  split_movie?: boolean;
  part_minutes?: number;
}

export interface SrtUpload {
  title: string;
  kind: TitleKind;
  season?: number;
  episode?: number;
  year?: number;
  splitMovie?: boolean;
  partMinutes?: number;
}

export interface LevelFilter {
  levels: StoredLevel[];
  include_unleveled: boolean;
  mwe_mode: MweMode;
}

export type FilterScope = "global" | "title" | "episode";

export interface LevelFilterView extends LevelFilter {
  source: FilterScope;
}

export interface ModuleSettings {
  user_level: CefrLevel;
  allow_answer_hints: boolean;
}

export interface ReanalyzeResult {
  candidates: number;
  archived: number;
  restored: number;
  job?: CardJob | null;
  failed?: string[];
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
  contextForWords: boolean;
  contextForExpressions: boolean;
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

export function importSrt(upload: SrtUpload, file: File): Promise<ImportedEpisode> {
  const form = new FormData();
  form.append("series_title", upload.title);
  form.append("kind", upload.kind);
  if (upload.season !== undefined) {
    form.append("season", String(upload.season));
  }
  if (upload.episode !== undefined) {
    form.append("episode", String(upload.episode));
  }
  if (upload.year !== undefined) {
    form.append("year", String(upload.year));
  }
  if (upload.splitMovie !== undefined) {
    form.append("split_movie", String(upload.splitMovie));
  }
  if (upload.partMinutes !== undefined) {
    form.append("part_minutes", String(upload.partMinutes));
  }
  form.append("file", file, file.name);
  return requestForm<ImportedEpisode>("/api/english/import/srt", form);
}

export function getEpisodeCards(episodeId: number, includeArchived = false): Promise<EnglishCard[]> {
  const query = includeArchived ? "?include_archived=true" : "";
  return requestJson<EnglishCard[]>(`/api/english/episodes/${episodeId}/cards${query}`);
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

export interface ListeningQuestion {
  cue_index: number;
  kind: "who" | "meaning" | "next" | string;
  question: string;
  options: string[];
  correct_index: number;
  start_ms: number;
  end_ms: number;
  line: string;
}

export interface ListeningQuiz {
  episode_id: number;
  video_name: string;
  questions: ListeningQuestion[];
}

export interface ListeningClip {
  audio_base64: string;
  mime: string;
}

export function getListeningQuiz(episodeId: number): Promise<ListeningQuiz> {
  return requestJson<ListeningQuiz>(`/api/english/episodes/${episodeId}/listening`);
}

export function createListeningQuiz(episodeId: number, videoPath: string): Promise<ListeningQuiz> {
  return requestJson<ListeningQuiz>(`/api/english/episodes/${episodeId}/listening`, {
    method: "POST",
    body: JSON.stringify({ video_path: videoPath }),
  });
}

export function getListeningClip(episodeId: number, cueIndex: number): Promise<ListeningClip> {
  return requestJson<ListeningClip>(`/api/english/episodes/${episodeId}/listening/clips/${cueIndex}`);
}

function scopeQuery(scope: FilterScope, scopeId?: number): string {
  return scope === "global" || scopeId === undefined ? `/api/english/filters/${scope}` : `/api/english/filters/${scope}?scope_id=${scopeId}`;
}

export function getLevelFilter(scope: FilterScope, scopeId?: number): Promise<LevelFilterView> {
  return requestJson<LevelFilterView>(scopeQuery(scope, scopeId));
}

export function saveLevelFilter(scope: FilterScope, filter: LevelFilter, scopeId?: number): Promise<LevelFilterView> {
  return requestJson<LevelFilterView>(scopeQuery(scope, scopeId), { method: "PUT", body: JSON.stringify(filter) });
}

export function resetLevelFilter(scope: FilterScope, scopeId?: number): Promise<LevelFilterView> {
  return requestJson<LevelFilterView>(scopeQuery(scope, scopeId), { method: "DELETE" });
}

export function getModuleSettings(): Promise<ModuleSettings> {
  return requestJson<ModuleSettings>("/api/english/settings");
}

export function saveModuleSettings(update: Partial<ModuleSettings>): Promise<ModuleSettings> {
  return requestJson<ModuleSettings>("/api/english/settings", { method: "PUT", body: JSON.stringify(update) });
}

export function reanalyzeEpisode(episodeId: number): Promise<ReanalyzeResult> {
  return requestJson<ReanalyzeResult>(`/api/english/episodes/${episodeId}/reanalyze`, { method: "POST" });
}

export function reanalyzeLibrary(): Promise<ReanalyzeResult> {
  return requestJson<ReanalyzeResult>("/api/english/reanalyze", { method: "POST" });
}

export interface DifficultyResult {
  title: string;
  kind: string;
  year: number | null;
  title_id: number | null;
  episodes_analyzed: number;
  coverage: number;
  verdict: "Подходит" | "Подходит с усилием" | "Пока рано";
  user_level: string;
  words_per_minute: number;
  above_level_count: number;
  examples: string[];
  distribution: Record<string, number>;
  factors: string[];
  small_sample: boolean;
  has_cards: boolean;
}

export interface AnalysisOffer {
  title: string;
  year: number | null;
  kind: string;
}

export interface AnalyzeResult {
  status: "analyzed" | "needs_input";
  title_id: number | null;
  message: string;
  options: string[];
}

export interface AboveLevelWord {
  lemma: string;
  level: string;
  count: number;
}

export function analyzeTitle(offer: AnalysisOffer): Promise<AnalyzeResult> {
  return requestJson<AnalyzeResult>("/api/english/assistant/analyze", { method: "POST", body: JSON.stringify(offer) });
}

export function generateTitleCards(titleId: number): Promise<{ jobs: number }> {
  return requestJson<{ jobs: number }>(`/api/english/assistant/titles/${titleId}/generate`, { method: "POST" });
}

export function wordsAboveLevel(titleId: number): Promise<AboveLevelWord[]> {
  return requestJson<AboveLevelWord[]>(`/api/english/assistant/titles/${titleId}/above-level`);
}
