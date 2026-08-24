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
  active_module_context: string | null;
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

export interface YouTubeStatus {
  key_configured: boolean;
  units_used: number;
  daily_limit: number;
  remaining_searches: number;
  near_limit: boolean;
  exhausted: boolean;
}

export interface GeminiKeyStatus {
  key_configured: boolean;
  requests_used_today: number;
  daily_limit: number;
}

export interface ClaudeKeyStatus {
  key_configured: boolean;
}

export interface SpotifyStatus {
  client_id_configured: boolean;
  connected: boolean;
  redirect_uri: string;
}

export interface GeneratedImage {
  id: number;
  prompt: string;
  source: string;
  created_at: string;
}

export interface GithubStatus {
  pat_configured: boolean;
}

export interface TelegramCredentialsStatus {
  configured: boolean;
}

export interface TelegramAccount {
  id: number;
  label: string;
  phone_number: string;
  connected: boolean;
}

export interface TelegramLoginCodeResult {
  needs_password: boolean;
  account: TelegramAccount | null;
}

export interface TelegramContact {
  id: number;
  identifier: string;
  note: string;
}

export interface PendingMessage {
  id: number;
  source: string;
  sender_label: string;
  text: string;
  received_at: string;
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

export type FitnessSex = "male" | "female";
export type FitnessGoalType = "weight" | "strength" | "volume";
export type FitnessConfidence = "high" | "medium" | "low";
export type FitnessMealSource = "photo" | "text" | "manual";

export interface FitnessBioProfile {
  sex: FitnessSex | null;
  age: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  bmi: number | null;
  bmi_category: string | null;
  updated_at: string;
}

export interface FitnessWeightHistoryEntry {
  weight_kg: number;
  recorded_at: string;
}

export interface FitnessMeasurement {
  id: number;
  body_part: string;
  value_cm: number;
  recorded_at: string;
}

export interface FitnessGoal {
  id: number;
  goal_type: FitnessGoalType;
  description: string;
  target_value: number | null;
  unit: string | null;
  deadline: string | null;
  created_at: string;
  achieved_at: string | null;
}

export interface FitnessMeal {
  id: number;
  description: string;
  estimated_calories: number | null;
  protein_g: number | null;
  fat_g: number | null;
  carbs_g: number | null;
  confidence: FitnessConfidence;
  source: FitnessMealSource;
  has_photo: boolean;
  logged_at: string;
}

export interface FitnessProgressPhoto {
  id: number;
  note: string | null;
  taken_at: string;
}

declare global {
  interface Window {
    assistantAPI?: AssistantWindowAPI;
  }
}
