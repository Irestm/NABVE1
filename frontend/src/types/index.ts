export type AssistantState =
  | "idle"
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

export interface CommunicationStyle {
  key: string;
  label: string;
  prosody_rate: number;
}

export interface CalendarEvent {
  id: number;
  title: string;
  event_time: string;
  remind_before_minutes: number;
  notified: boolean;
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

declare global {
  interface Window {
    assistantAPI?: AssistantWindowAPI;
  }
}
