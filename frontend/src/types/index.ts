export type AssistantState =
  | "idle"
  | "background_listening"
  | "listening"
  | "processing"
  | "thinking"
  | "speaking"
  | "error"
  | "paused";

export interface StatusResponse {
  state: AssistantState;
  detail: string;
}

export type ProviderName = "gemini" | "chatgpt" | "deepseek" | "grok";

export interface AIBridgeStatus {
  active_provider: ProviderName;
  order: ProviderName[];
  last_reset_date: string;
  limit_reached: Record<string, boolean>;
  logged_in: Record<string, boolean>;
}

export interface UIVisibilityRequest {
  action: "show" | "hide" | null;
}

export interface ImageRequest {
  // Plain SVG text (not base64) — see core/state.py::StateManager.request_image.
  svg: string | null;
}

export type CommandStatus = "executed" | "confirmation_required" | "cancelled" | "failed";

export interface CommandResponse {
  status: CommandStatus;
  command: string;
  message: string;
  token: string | null;
  result: Record<string, unknown> | null;
}

export interface CommandDescriptor {
  name: string;
  dangerous: boolean;
  description: string;
}

export interface CommandParamField {
  name: string;
  type: "number" | "text" | "select";
  label: string;
  min: number | null;
  max: number | null;
  options: string[] | null;
  optional: boolean;
}

export interface CommandButtonDescriptor {
  name: string;
  label: string;
  icon: string;
  dangerous: boolean;
  description: string;
  params_schema: CommandParamField[] | null;
}

export interface CommunicationStyle {
  key: string;
  label: string;
  prosody_rate: number;
}

// Matches core/models.py... actually calendar events have no dedicated
// Pydantic model — they travel through the generic dispatcher command
// result (see modules/calendar/handlers.py), so this interface is the
// single source of truth for that shape on the frontend side.
export type RecurrenceRule = "none" | "daily" | "weekly" | "monthly" | "yearly";

export interface CalendarEvent {
  id: number;
  title: string;
  event_time: string;
  remind_before_minutes: number;
  notified: boolean;
  color: string | null;
  category: string | null;
  recurrence: RecurrenceRule;
}

export interface PluginSuggestion {
  id: number;
  description: string;
  message: string;
  status: string;
  plugin_name: string | null;
  safety_flags: string[];
  requires_manual_review: boolean;
  created_at: string;
  last_seen: string;
}

// Matches core/models.py's CustomCommandResponse and
// modules/custom_commands/domain.py's ActionType exactly.
export type CustomCommandActionType = "open_link" | "play_audio" | "open_media" | "launch_app" | "text_instruction";

export interface CustomCommand {
  id: string;
  trigger_phrase: string;
  action_type: CustomCommandActionType;
  action_payload: Record<string, string>;
  created_at: string;
}

export interface VoiceQueryResponse {
  transcribed_text: string;
  reply_text: string;
  language: string;
  audio_wav_base64: string | null;
  status: CommandStatus | null;
  token: string | null;
}

export interface SpeakResponse {
  audio_wav_base64: string | null;
}

export interface LanUrlResponse {
  url: string;
}

export interface VoiceOption {
  speaker: string;
  label: string;
  gender: "male" | "female";
}

export interface VoiceOptionsResponse {
  voices: VoiceOption[];
  selected: string;
}

export interface AssistantWindowAPI {
  backendBaseUrl: string;
  // The shared secret every /api/* request must present (see
  // core/main.py's require_api_token middleware and
  // frontend/src/api/client.ts). Generated once by the Electron main
  // process and handed to the backend it spawns and to this renderer via
  // preload's additionalArguments — see frontend/electron/main.ts and
  // preload.ts. Undefined outside Electron, where the token instead comes
  // from the LAN QR code's ?token= (see client.ts's resolveApiToken).
  apiToken?: string;
  // Lets the Electron main process gate the window's close/quit behavior
  // behind a confirmation dialog only while a meeting recording is actually
  // active — see frontend/electron/main.ts and
  // frontend/src/meeting/meetingRecorder.ts. No-op outside Electron (the
  // whole object is undefined there — see platform/electronAdapter.ts).
  setRecordingActive?: (active: boolean) => void;
  // Opens a native "choose an executable" file dialog on the machine
  // running the Electron main process (see frontend/electron/main.ts's
  // "pick-executable" ipcMain.handle) and resolves to the chosen absolute
  // path, or null if cancelled. Undefined outside Electron — a plain
  // browser/LAN thin client can't browse the assistant host's filesystem,
  // so components/CustomCommandsPanel.tsx falls back to manual path entry
  // when this is absent. Used only for the launch_app custom-command
  // form's "Обзор…" button.
  pickExecutablePath?: () => Promise<string | null>;
}

export type MeetingRecordingStatus = "uploading" | "processing" | "ready" | "error";
export type MeetingTranscriptStatus = "pending" | "transcribing" | "done" | "error";
export type MeetingSummaryStatus = "pending" | "generating" | "done" | "error" | "skipped";

export interface MeetingRecording {
  id: number;
  created_at: string;
  status: MeetingRecordingStatus;
  error: string | null;
  duration_seconds: number | null;
  size_bytes: number;
  mic_only: boolean;
  context_label: string | null;
  transcript_status: MeetingTranscriptStatus;
  transcript_progress: number;
  transcript_error: string | null;
  summary_status: MeetingSummaryStatus;
  summary_error: string | null;
}

// Matches core/models.py's SetSource-derived `source` string and
// modules/quizlet_clone/models.py's SetSource/GameMode enums exactly.
export type StudySetSource = "quizlet_import" | "manual";
export type GameMode = "flashcards" | "learn" | "match" | "test" | "voice";

export interface QuizletAuthStatus {
  logged_in: boolean;
}

export interface StudySetTerm {
  id: string;
  term: string;
  definition: string;
  times_seen: number;
  times_correct: number;
  times_wrong: number;
  learned: boolean;
}

export interface StudySet {
  id: string;
  title: string;
  source: StudySetSource;
  quizlet_set_id: string | null;
  created_at: string;
  progress_percent: number;
  attempts_count: number;
  terms: StudySetTerm[];
}

export interface QuizletLibrarySet {
  quizlet_set_id: string;
  title: string;
  term_count: number;
  already_imported: boolean;
  local_set_id: string | null;
}

// The shape of `state` varies by mode (see modules/quizlet_clone/game_modes.py's
// per-session state() methods) — kept loosely typed here rather than one
// strict interface per mode, and narrowed with optional fields the
// game-mode components read defensively.
export interface QuizletGameState {
  mode: GameMode;
  finished: boolean;
  index?: number;
  total?: number;
  remaining?: number;
  score?: number;
  flipped?: boolean;
  term?: string;
  term_id?: string;
  definition?: string;
  type?: "input" | "choice";
  options?: string[];
  tiles?: { tile_id: string; text: string; kind: "term" | "definition"; matched: boolean }[];
  matched_count?: number;
  elapsed_seconds?: number | null;
  last_attempt?: { first_tile_id: string; second_tile_id: string; correct: boolean } | null;
  last_answer?: { term_id: string; correct: boolean; correct_definition: string } | null;
}

export interface QuizletGameStateResponse {
  session_id: string;
  state: QuizletGameState;
}

export interface QuizletVoiceGameStartResponse {
  session_id: string;
  finished: boolean;
  term_text: string | null;
  term_audio_base64: string | null;
  remaining: number;
  total: number;
}

export interface QuizletVoiceGameAnswerResponse {
  session_id: string;
  transcribed_text: string;
  correct: boolean;
  answered_term: string;
  expected_definition: string;
  result_audio_base64: string | null;
  finished: boolean;
  next_term_text: string | null;
  next_term_audio_base64: string | null;
  remaining: number;
  total: number;
}

export type BoardGameKind = "chess" | "checkers";

export type BoardGameDifficulty = "very_easy" | "easy" | "medium" | "hard" | "very_hard" | "impossible";

export interface LegalMoveSquares {
  from_square: string;
  to_square: string;
  label: string;
}

export interface BoardGameState {
  kind: BoardGameKind;
  difficulty: BoardGameDifficulty | null;
  board_svg: string;
  legal_moves: string[];
  legal_move_squares: LegalMoveSquares[];
  is_over: boolean;
  is_check: boolean;
  result: string | null;
  last_player_move: string | null;
  last_engine_move: string | null;
  last_engine_move_from: string | null;
  last_engine_move_to: string | null;
  mistake_message: string | null;
}

declare global {
  interface Window {
    assistantAPI?: AssistantWindowAPI;
  }
}
