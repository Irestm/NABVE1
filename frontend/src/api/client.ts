import type {
  AIBridgeStatus,
  BoardGameDifficulty,
  BoardGameKind,
  BoardGameState,
  CalendarEvent,
  CommandButtonDescriptor,
  CommandDescriptor,
  CommandResponse,
  CommunicationStyle,
  CustomCommand,
  CustomCommandActionType,
  GameMode,
  ImageRequest,
  LanUrlResponse,
  MeetingRecording,
  PluginSuggestion,
  QuizletAuthStatus,
  RecurrenceRule,
  QuizletGameStateResponse,
  QuizletLibrarySet,
  QuizletVoiceGameAnswerResponse,
  QuizletVoiceGameStartResponse,
  SpeakResponse,
  StatusResponse,
  StudySet,
  VoiceOptionsResponse,
  VoiceQueryResponse,
} from "../types";

// Electron always provides an absolute backendBaseUrl (its preload script
// injects it — see frontend/electron/preload.ts) because the renderer and
// the FastAPI backend run on different ports even in production. A plain
// browser has no such thing: when this app is opened as a thin client (either
// directly from FastAPI's static mount, or from the Vite dev server proxied
// the same way), relative paths are correct and work for any host/IP without
// hardcoding one — which is exactly what makes it work unmodified from a
// phone on the LAN.
const BASE_URL: string = window.assistantAPI?.backendBaseUrl ?? "";

const API_TOKEN_STORAGE_KEY = "assistantApiToken";

// core/main.py's require_api_token middleware rejects every /api/* request
// that doesn't carry this — see that middleware's own docstring for why.
// Electron gets it synchronously from preload (see electron/preload.ts).
// A phone/browser thin client instead gets it from the LAN QR code's
// ?token= query param (see core/main.py's get_lan_url) the first time it
// loads the page; from then on it's kept in localStorage so reloading or
// bookmarking the plain URL (without the query param) still works. The
// param is stripped from the visible URL right after reading it so it
// doesn't linger in browser history/screenshots.
function resolveApiToken(): string {
  const injected = window.assistantAPI?.apiToken;
  if (injected) {
    return injected;
  }
  if (typeof window === "undefined" || !window.location) {
    return "";
  }
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    try {
      window.localStorage.setItem(API_TOKEN_STORAGE_KEY, fromUrl);
    } catch (error) {
      // Storage unavailable (private mode, ...) — token still works for
      // this page load via `API_TOKEN` below, just won't survive a reload.
      console.error("Failed to persist the API token to localStorage:", error);
    }
    params.delete("token");
    const rest = params.toString();
    const cleanUrl = `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", cleanUrl);
    return fromUrl;
  }
  try {
    return window.localStorage.getItem(API_TOKEN_STORAGE_KEY) ?? "";
  } catch (error) {
    console.error("Failed to read the API token from localStorage:", error);
    return "";
  }
}

const API_TOKEN: string = resolveApiToken();

function authHeaders(extra?: HeadersInit): Record<string, string> {
  return { "X-Assistant-Token": API_TOKEN, ...(extra as Record<string, string> | undefined) };
}

// Appends ?token= to a URL that's handed to something other than fetch()
// (an <audio> element's src, in particular) and so can't carry a custom
// header — see getMeetingRecordingAudioUrl below.
function withTokenParam(url: string): string {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(API_TOKEN)}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(init?.headers) },
  });
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/api/status");
}

export function listCommands(): Promise<CommandDescriptor[]> {
  return requestJson<CommandDescriptor[]>("/api/commands");
}

export function listCommandButtons(): Promise<CommandButtonDescriptor[]> {
  return requestJson<CommandButtonDescriptor[]>("/api/commands/ui");
}

export function runCommand(
  command: string,
  params: Record<string, unknown> = {},
): Promise<CommandResponse> {
  return requestJson<CommandResponse>("/api/command", {
    method: "POST",
    body: JSON.stringify({ command, params }),
  });
}

export function confirmCommand(token: string, approved: boolean): Promise<CommandResponse> {
  return requestJson<CommandResponse>("/api/command/confirm", {
    method: "POST",
    body: JSON.stringify({ token, approved }),
  });
}

export function startBoardGame(kind: BoardGameKind, difficulty: BoardGameDifficulty | null): Promise<BoardGameState> {
  return requestJson<BoardGameState>("/api/boardgames/start", {
    method: "POST",
    body: JSON.stringify({ kind, difficulty }),
  });
}

export function getCurrentBoardGame(): Promise<BoardGameState | null> {
  return requestJson<BoardGameState | null>("/api/boardgames/current");
}

export function playBoardGameMove(notation: string): Promise<BoardGameState> {
  return requestJson<BoardGameState>("/api/boardgames/move", {
    method: "POST",
    body: JSON.stringify({ notation }),
  });
}

export function finishBoardGame(): Promise<{ message: string }> {
  return requestJson<{ message: string }>("/api/boardgames/finish", { method: "POST" });
}

export function getAIBridgeStatus(): Promise<AIBridgeStatus> {
  return requestJson<AIBridgeStatus>("/api/ai_bridge/status");
}

// Polled by BoardGameImageModal to show the chess/draughts board rendered at
// the end of a voice game — see core/state.py::StateManager.request_image.
export function getImageRequest(): Promise<ImageRequest> {
  return requestJson<ImageRequest>("/api/ui/image_request");
}

export async function listPluginSuggestions(): Promise<PluginSuggestion[]> {
  const response = await runCommand("plugin_agent_list_suggestions");
  const suggestions = response.result?.suggestions;
  return Array.isArray(suggestions) ? (suggestions as PluginSuggestion[]) : [];
}

export async function getPluginSuggestionCode(suggestionId: number): Promise<string> {
  const response = await runCommand("plugin_agent_get_code", { suggestion_id: suggestionId });
  const code = response.result?.code;
  return typeof code === "string" ? code : "";
}

export function approvePluginSuggestion(suggestionId: number): Promise<CommandResponse> {
  return runCommand("plugin_agent_approve", { suggestion_id: suggestionId });
}

export function rejectPluginSuggestion(suggestionId: number): Promise<CommandResponse> {
  return runCommand("plugin_agent_reject", { suggestion_id: suggestionId });
}

export async function listUpcomingEvents(limit = 50): Promise<CalendarEvent[]> {
  const response = await runCommand("calendar_list_upcoming", { limit });
  const events = response.result?.events;
  return Array.isArray(events) ? (events as CalendarEvent[]) : [];
}

export function createCalendarEvent(
  title: string,
  eventTimeIso: string,
  remindBeforeMinutes: number,
  color: string | null = null,
  category: string | null = null,
  recurrence: RecurrenceRule = "none",
): Promise<CommandResponse> {
  return runCommand("calendar_create_event", {
    title,
    event_time: eventTimeIso,
    remind_before_minutes: remindBeforeMinutes,
    color,
    category,
    recurrence,
  });
}

export function deleteCalendarEvent(eventId: number): Promise<CommandResponse> {
  return runCommand("calendar_delete_event", { event_id: eventId });
}

export async function listCommunicationStyles(): Promise<CommunicationStyle[]> {
  const response = await runCommand("list_communication_styles");
  const styles = response.result?.styles;
  return Array.isArray(styles) ? (styles as CommunicationStyle[]) : [];
}

export async function getProfileFact(key: string): Promise<string | null> {
  const response = await runCommand("profile_get", { key });
  const value = response.result?.value;
  return typeof value === "string" ? value : null;
}

export async function setProfileFact(key: string, value: string): Promise<void> {
  await runCommand("profile_set", { key, value });
}

export async function saveAboutMe(text: string): Promise<string[]> {
  const response = await runCommand("profile_save_about_me", { text });
  const extractedKeys = response.result?.extracted_keys;
  return Array.isArray(extractedKeys) ? (extractedKeys as string[]) : [];
}

export async function sendVoiceQuery(
  audio: Blob,
  filename = "query.webm",
  language?: string | null,
): Promise<VoiceQueryResponse> {
  const form = new FormData();
  form.append("audio", audio, filename);
  if (language) {
    form.append("language", language);
  }
  const response = await fetch(`${BASE_URL}/api/voice/query`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Voice query failed with status ${response.status}`);
  }
  return (await response.json()) as VoiceQueryResponse;
}

export async function sendVoiceConfirmation(
  audio: Blob,
  token: string,
  filename = "confirm.webm",
  language?: string | null,
): Promise<VoiceQueryResponse> {
  const form = new FormData();
  form.append("audio", audio, filename);
  form.append("token", token);
  if (language) {
    form.append("language", language);
  }
  const response = await fetch(`${BASE_URL}/api/voice/confirm`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Voice confirmation failed with status ${response.status}`);
  }
  return (await response.json()) as VoiceQueryResponse;
}

export function sendTextQuery(text: string, language?: string | null): Promise<VoiceQueryResponse> {
  return requestJson<VoiceQueryResponse>("/api/voice/text_query", {
    method: "POST",
    body: JSON.stringify({ text, language: language ?? null }),
  });
}

export function speak(text: string, language: string, speaker?: string): Promise<SpeakResponse> {
  return requestJson<SpeakResponse>("/api/voice/speak", {
    method: "POST",
    body: JSON.stringify({ text, language, speaker: speaker ?? null }),
  });
}

export function getLanUrl(): Promise<LanUrlResponse> {
  return requestJson<LanUrlResponse>("/api/lan_url");
}

export function getVoiceOptions(): Promise<VoiceOptionsResponse> {
  return requestJson<VoiceOptionsResponse>("/api/voice/voices");
}

export function selectVoice(speaker: string): Promise<VoiceOptionsResponse> {
  return requestJson<VoiceOptionsResponse>("/api/voice/voices/select", {
    method: "POST",
    body: JSON.stringify({ speaker }),
  });
}

export async function listCustomCommands(): Promise<CustomCommand[]> {
  const response = await requestJson<{ commands: CustomCommand[] }>("/api/custom_commands");
  return response.commands;
}

// Matches core/main.py's create_or_update_custom_command Form fields —
// commandId omitted means create, set means update. One multipart route
// handles every action_type (only play_audio/open_media actually attach
// a file), see that route's own docstring for why.
export interface SaveCustomCommandInput {
  commandId?: string | undefined;
  triggerPhrase: string;
  actionType: CustomCommandActionType;
  url?: string | undefined;
  executablePath?: string | undefined;
  instruction?: string | undefined;
  mediaType?: "photo" | "video" | undefined;
  file?: File | null;
}

export async function saveCustomCommand(input: SaveCustomCommandInput): Promise<CustomCommand> {
  const form = new FormData();
  form.append("trigger_phrase", input.triggerPhrase);
  form.append("action_type", input.actionType);
  if (input.commandId) {
    form.append("command_id", input.commandId);
  }
  if (input.url) {
    form.append("url", input.url);
  }
  if (input.executablePath) {
    form.append("executable_path", input.executablePath);
  }
  if (input.instruction) {
    form.append("instruction", input.instruction);
  }
  if (input.mediaType) {
    form.append("media_type", input.mediaType);
  }
  if (input.file) {
    form.append("file", input.file);
  }

  const response = await fetch(`${BASE_URL}/api/custom_commands`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Saving the custom command failed with status ${response.status}`);
  }
  return (await response.json()) as CustomCommand;
}

export async function deleteCustomCommand(commandId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/custom_commands/${encodeURIComponent(commandId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Deleting the custom command failed with status ${response.status}`);
  }
}

export async function createMeetingRecording(contextLabel?: string | null): Promise<number> {
  const response = await requestJson<{ id: number }>("/api/meetings/recordings", {
    method: "POST",
    body: JSON.stringify({ context_label: contextLabel ?? null }),
  });
  return response.id;
}

// Sent as a raw binary body (not FormData/JSON): the client streams one
// MediaRecorder `ondataavailable` blob per call through the life of a
// single recording, and the backend just appends bytes to a file — see
// core/main.py's POST /api/meetings/recordings/{id}/chunk.
export async function uploadMeetingRecordingChunk(recordingId: number, chunk: Blob): Promise<number> {
  const response = await fetch(`${BASE_URL}/api/meetings/recordings/${recordingId}/chunk`, {
    method: "POST",
    body: chunk,
    headers: authHeaders(),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`Chunk upload failed with status ${response.status}: ${detail}`);
  }
  const body = (await response.json()) as { size_bytes: number };
  return body.size_bytes;
}

export function finishMeetingRecording(recordingId: number, micOnly: boolean): Promise<MeetingRecording> {
  return requestJson<MeetingRecording>(`/api/meetings/recordings/${recordingId}/finish`, {
    method: "POST",
    body: JSON.stringify({ mic_only: micOnly }),
  });
}

export function listMeetingRecordings(): Promise<MeetingRecording[]> {
  return requestJson<MeetingRecording[]>("/api/meetings/recordings");
}

export function getMeetingRecording(recordingId: number): Promise<MeetingRecording> {
  return requestJson<MeetingRecording>(`/api/meetings/recordings/${recordingId}`);
}

// A plain URL, not a fetch() call — this is handed straight to an <audio>
// element's src (see the meetings UI), which can't attach a custom header,
// hence the token travels as a query param here instead (see
// withTokenParam / core/main.py's require_api_token).
export function getMeetingRecordingAudioUrl(recordingId: number): string {
  return withTokenParam(`${BASE_URL}/api/meetings/recordings/${recordingId}/audio`);
}

// Same withTokenParam pattern — an <a href download> link can't carry a
// custom header either. Each zip already has this machine's address/token
// (WordPress/Figma) or nothing to fill in at all (Blender) baked in — see
// modules/integrations/packager.py.
export function getWordpressPluginDownloadUrl(): string {
  return withTokenParam(`${BASE_URL}/api/integrations/wordpress/plugin.zip`);
}

export function getFigmaPluginDownloadUrl(): string {
  return withTokenParam(`${BASE_URL}/api/integrations/figma/plugin.zip`);
}

export function getBlenderAddonDownloadUrl(): string {
  return withTokenParam(`${BASE_URL}/api/integrations/blender/addon.zip`);
}

export async function getMeetingRecordingTranscript(recordingId: number): Promise<string> {
  const response = await requestJson<{ text: string }>(
    `/api/meetings/recordings/${recordingId}/transcript`,
  );
  return response.text;
}

export async function getMeetingRecordingSummary(recordingId: number): Promise<string> {
  const response = await requestJson<{ text: string }>(`/api/meetings/recordings/${recordingId}/summary`);
  return response.text;
}

export async function deleteMeetingRecording(
  recordingId: number,
): Promise<{ deleted: boolean; pending: boolean }> {
  const response = await fetch(`${BASE_URL}/api/meetings/recordings/${recordingId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Delete failed with status ${response.status}`);
  }
  return (await response.json()) as { deleted: boolean; pending: boolean };
}

// --- modules/quizlet_clone ---------------------------------------------

export function getQuizletStatus(): Promise<QuizletAuthStatus> {
  return requestJson<QuizletAuthStatus>("/api/quizlet/status");
}

// Login/logout/import go through the generic dispatcher (like
// ai_bridge_provider_login/logout above) rather than dedicated REST
// routes — see modules/quizlet_clone/handlers.py.
export function quizletLogin(): Promise<CommandResponse> {
  return runCommand("quizlet_login");
}

export function quizletLogout(): Promise<CommandResponse> {
  return runCommand("quizlet_logout");
}

export function quizletImportSession(): Promise<CommandResponse> {
  return runCommand("quizlet_import_session");
}

export function quizletImportAllSets(): Promise<CommandResponse> {
  return runCommand("quizlet_import_all_sets");
}

export function quizletImportSet(quizletSetId: string, title: string): Promise<CommandResponse> {
  return runCommand("quizlet_import_set", { quizlet_set_id: quizletSetId, title });
}

export async function listQuizletLibrary(): Promise<QuizletLibrarySet[]> {
  const response = await requestJson<{ sets: QuizletLibrarySet[] }>("/api/quizlet/library");
  return response.sets;
}

export async function listStudySets(): Promise<StudySet[]> {
  const response = await requestJson<{ sets: StudySet[] }>("/api/quizlet/sets");
  return response.sets;
}

export function saveStudySet(
  setId: string | undefined,
  title: string,
  terms: { term: string; definition: string }[],
): Promise<StudySet> {
  return requestJson<StudySet>("/api/quizlet/sets", {
    method: "POST",
    body: JSON.stringify({ set_id: setId ?? null, title, terms }),
  });
}

export async function deleteStudySet(setId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/quizlet/sets/${encodeURIComponent(setId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Deleting the study set failed with status ${response.status}`);
  }
}

export function startQuizletGame(setId: string, mode: GameMode): Promise<QuizletGameStateResponse> {
  return requestJson<QuizletGameStateResponse>("/api/quizlet/game/start", {
    method: "POST",
    body: JSON.stringify({ set_id: setId, mode }),
  });
}

export function getQuizletGameState(sessionId: string): Promise<QuizletGameStateResponse> {
  return requestJson<QuizletGameStateResponse>(`/api/quizlet/game/${encodeURIComponent(sessionId)}`);
}

export function answerQuizletGame(
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<QuizletGameStateResponse> {
  return requestJson<QuizletGameStateResponse>(`/api/quizlet/game/${encodeURIComponent(sessionId)}/answer`, {
    method: "POST",
    body: JSON.stringify({ payload }),
  });
}

export function startQuizletVoiceGame(setId: string): Promise<QuizletVoiceGameStartResponse> {
  return requestJson<QuizletVoiceGameStartResponse>("/api/quizlet/voice/start", {
    method: "POST",
    body: JSON.stringify({ set_id: setId, mode: "voice" }),
  });
}

export async function answerQuizletVoiceGame(
  sessionId: string,
  audio: Blob,
  filename = "answer.webm",
): Promise<QuizletVoiceGameAnswerResponse> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("audio", audio, filename);
  const response = await fetch(`${BASE_URL}/api/quizlet/voice/answer`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Voice answer failed with status ${response.status}`);
  }
  return (await response.json()) as QuizletVoiceGameAnswerResponse;
}
