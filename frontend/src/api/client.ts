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
  ImageRequest,
  LanUrlResponse,
  MeetingRecording,
  PluginSuggestion,
  RecurrenceRule,
  ClaudeKeyStatus,
  FitnessBioProfile,
  FitnessGoal,
  FitnessGoalType,
  FitnessMeal,
  FitnessMeasurement,
  FitnessProgressPhoto,
  FitnessWeightHistoryEntry,
  GeminiKeyStatus,
  GeneratedImage,
  GithubStatus,
  PendingMessage,
  SpeakResponse,
  SpotifyStatus,
  StatusResponse,
  TelegramAccount,
  TelegramContact,
  TelegramCredentialsStatus,
  TelegramLoginCodeResult,
  VoiceLoopSignalResult,
  VoiceOptionsResponse,
  VoiceQueryResponse,
  YouTubeStatus,
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
    // FastAPI's HTTPException body is {"detail": "..."} — that's the actual,
    // specific reason ("Сначала войдите в Quizlet", "Quizlet изменил
    // структуру страницы", ...) callers need to show the user instead of a
    // bare status code. Falls back to the status-code message only when the
    // body isn't JSON or has no `detail` at all (a non-FastAPI failure, e.g.
    // a proxy/network error page).
    const detail = await response
      .json()
      .then((body: unknown) =>
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : null,
      )
      .catch(() => null);
    throw new Error(detail ?? `Request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/api/status");
}

// Both drive the same always-on backend voice loop VoiceRecorder.tsx's
// Electron branch uses instead of a second, browser-side microphone — see
// core/main.py's /api/voice/trigger and /api/voice/pause docstrings.
export function triggerVoiceLoop(): Promise<VoiceLoopSignalResult> {
  return requestJson<VoiceLoopSignalResult>("/api/voice/trigger", { method: "POST" });
}

export function pauseVoiceLoop(): Promise<VoiceLoopSignalResult> {
  return requestJson<VoiceLoopSignalResult>("/api/voice/pause", { method: "POST" });
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

export async function transcribeAudio(
  audio: Blob,
  filename = "input.webm",
  language?: string | null,
): Promise<string> {
  const form = new FormData();
  form.append("audio", audio, filename);
  if (language) {
    form.append("language", language);
  }
  const response = await fetch(`${BASE_URL}/api/voice/transcribe`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Transcription failed with status ${response.status}`);
  }
  const body = (await response.json()) as { text: string };
  return body.text;
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

export function getYoutubeStatus(): Promise<YouTubeStatus> {
  return requestJson<YouTubeStatus>("/api/youtube/status");
}

export function saveYoutubeApiKey(apiKey: string): Promise<YouTubeStatus> {
  return requestJson<YouTubeStatus>("/api/youtube/api_key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteYoutubeApiKey(): Promise<YouTubeStatus> {
  return requestJson<YouTubeStatus>("/api/youtube/api_key", { method: "DELETE" });
}

export function getGeminiKeyStatus(): Promise<GeminiKeyStatus> {
  return requestJson<GeminiKeyStatus>("/api/ai_bridge/gemini_api_key");
}

export function saveGeminiApiKey(apiKey: string): Promise<GeminiKeyStatus> {
  return requestJson<GeminiKeyStatus>("/api/ai_bridge/gemini_api_key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteGeminiApiKey(): Promise<GeminiKeyStatus> {
  return requestJson<GeminiKeyStatus>("/api/ai_bridge/gemini_api_key", { method: "DELETE" });
}

export function getClaudeKeyStatus(): Promise<ClaudeKeyStatus> {
  return requestJson<ClaudeKeyStatus>("/api/ai_bridge/claude_api_key");
}

export function saveClaudeApiKey(apiKey: string): Promise<ClaudeKeyStatus> {
  return requestJson<ClaudeKeyStatus>("/api/ai_bridge/claude_api_key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteClaudeApiKey(): Promise<ClaudeKeyStatus> {
  return requestJson<ClaudeKeyStatus>("/api/ai_bridge/claude_api_key", { method: "DELETE" });
}

export function getGithubPatStatus(): Promise<GithubStatus> {
  return requestJson<GithubStatus>("/api/integrations/github_pat");
}

export function saveGithubPat(pat: string): Promise<GithubStatus> {
  return requestJson<GithubStatus>("/api/integrations/github_pat", {
    method: "POST",
    body: JSON.stringify({ pat }),
  });
}

export function deleteGithubPat(): Promise<GithubStatus> {
  return requestJson<GithubStatus>("/api/integrations/github_pat", { method: "DELETE" });
}

export function getTelegramCredentialsStatus(): Promise<TelegramCredentialsStatus> {
  return requestJson<TelegramCredentialsStatus>("/api/telegram/credentials");
}

export function saveTelegramCredentials(apiId: number, apiHash: string): Promise<TelegramCredentialsStatus> {
  return requestJson<TelegramCredentialsStatus>("/api/telegram/credentials", {
    method: "POST",
    body: JSON.stringify({ api_id: apiId, api_hash: apiHash }),
  });
}

export function listTelegramAccounts(): Promise<TelegramAccount[]> {
  return requestJson<TelegramAccount[]>("/api/telegram/accounts");
}

export async function deleteTelegramAccount(accountId: number): Promise<void> {
  await requestJson(`/api/telegram/accounts/${accountId}`, { method: "DELETE" });
}

export async function startTelegramLogin(label: string, phoneNumber: string): Promise<string> {
  const response = await requestJson<{ token: string }>("/api/telegram/accounts/login/start", {
    method: "POST",
    body: JSON.stringify({ label, phone_number: phoneNumber }),
  });
  return response.token;
}

export function submitTelegramLoginCode(token: string, code: string): Promise<TelegramLoginCodeResult> {
  return requestJson<TelegramLoginCodeResult>("/api/telegram/accounts/login/code", {
    method: "POST",
    body: JSON.stringify({ token, code }),
  });
}

export function submitTelegramLoginPassword(token: string, password: string): Promise<TelegramAccount> {
  return requestJson<TelegramAccount>("/api/telegram/accounts/login/password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

export function listTelegramContacts(): Promise<TelegramContact[]> {
  return requestJson<TelegramContact[]>("/api/telegram/contacts");
}

export function addTelegramContact(identifier: string, note = ""): Promise<TelegramContact> {
  return requestJson<TelegramContact>("/api/telegram/contacts", {
    method: "POST",
    body: JSON.stringify({ identifier, note }),
  });
}

export async function deleteTelegramContact(contactId: number): Promise<void> {
  await requestJson(`/api/telegram/contacts/${contactId}`, { method: "DELETE" });
}

export function listPendingMessages(): Promise<PendingMessage[]> {
  return requestJson<PendingMessage[]>("/api/messaging/pending");
}

export function getSpotifyStatus(): Promise<SpotifyStatus> {
  return requestJson<SpotifyStatus>("/api/spotify/status");
}

export function saveSpotifyClientId(clientId: string): Promise<SpotifyStatus> {
  return requestJson<SpotifyStatus>("/api/spotify/client_id", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId }),
  });
}

export async function startSpotifyLogin(): Promise<string> {
  const response = await requestJson<{ authorize_url: string }>("/api/spotify/login", { method: "POST" });
  return response.authorize_url;
}

export function disconnectSpotify(): Promise<SpotifyStatus> {
  return requestJson<SpotifyStatus>("/api/spotify/connection", { method: "DELETE" });
}

export async function listGeneratedImages(): Promise<GeneratedImage[]> {
  return requestJson<GeneratedImage[]>("/api/images");
}

export function getGeneratedImageFileUrl(imageId: number): string {
  return withTokenParam(`${BASE_URL}/api/images/${imageId}/file`);
}

export async function deleteGeneratedImage(imageId: number): Promise<void> {
  await requestJson(`/api/images/${imageId}`, { method: "DELETE" });
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

export function getFitnessProfile(): Promise<FitnessBioProfile | null> {
  return requestJson<FitnessBioProfile | null>("/api/fitness/profile");
}

export interface FitnessBioProfileUpdate {
  sex?: string | null;
  age?: number | null;
  height_cm?: number | null;
  weight_kg?: number | null;
}

export function updateFitnessProfile(update: FitnessBioProfileUpdate): Promise<FitnessBioProfile> {
  return requestJson<FitnessBioProfile>("/api/fitness/profile", {
    method: "POST",
    body: JSON.stringify(update),
  });
}

export function getFitnessWeightHistory(): Promise<FitnessWeightHistoryEntry[]> {
  return requestJson<FitnessWeightHistoryEntry[]>("/api/fitness/weight_history");
}

export function listFitnessMeasurements(bodyPart?: string): Promise<FitnessMeasurement[]> {
  const query = bodyPart ? `?body_part=${encodeURIComponent(bodyPart)}` : "";
  return requestJson<FitnessMeasurement[]>(`/api/fitness/measurements${query}`);
}

export function addFitnessMeasurement(bodyPart: string, valueCm: number): Promise<FitnessMeasurement> {
  return requestJson<FitnessMeasurement>("/api/fitness/measurements", {
    method: "POST",
    body: JSON.stringify({ body_part: bodyPart, value_cm: valueCm }),
  });
}

export function listFitnessGoals(): Promise<FitnessGoal[]> {
  return requestJson<FitnessGoal[]>("/api/fitness/goals");
}

export function addFitnessGoal(
  goalType: FitnessGoalType,
  description: string,
  targetValue?: number | null,
  unit?: string | null,
  deadline?: string | null,
): Promise<FitnessGoal> {
  return requestJson<FitnessGoal>("/api/fitness/goals", {
    method: "POST",
    body: JSON.stringify({
      goal_type: goalType,
      description,
      target_value: targetValue ?? null,
      unit: unit ?? null,
      deadline: deadline ?? null,
    }),
  });
}

export async function deleteFitnessGoal(goalId: number): Promise<void> {
  await requestJson(`/api/fitness/goals/${goalId}`, { method: "DELETE" });
}

export function listFitnessMeals(limit?: number): Promise<FitnessMeal[]> {
  const query = limit ? `?limit=${limit}` : "";
  return requestJson<FitnessMeal[]>(`/api/fitness/meals${query}`);
}

export function logFitnessMealText(description: string, grams?: number | null): Promise<FitnessMeal> {
  return requestJson<FitnessMeal>("/api/fitness/meals/text", {
    method: "POST",
    body: JSON.stringify({ description, grams: grams ?? null }),
  });
}

export async function logFitnessMealPhoto(photo: File, note?: string): Promise<FitnessMeal> {
  const form = new FormData();
  form.append("photo", photo);
  if (note) {
    form.append("note", note);
  }
  const response = await fetch(`${BASE_URL}/api/fitness/meals/photo`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Meal photo upload failed with status ${response.status}`);
  }
  return (await response.json()) as FitnessMeal;
}

export function getFitnessMealPhotoUrl(mealId: number): string {
  return withTokenParam(`${BASE_URL}/api/fitness/meals/${mealId}/photo`);
}

export async function deleteFitnessMeal(mealId: number): Promise<void> {
  await requestJson(`/api/fitness/meals/${mealId}`, { method: "DELETE" });
}

export function listFitnessProgressPhotos(): Promise<FitnessProgressPhoto[]> {
  return requestJson<FitnessProgressPhoto[]>("/api/fitness/progress_photos");
}

export async function addFitnessProgressPhoto(photo: File, note?: string): Promise<FitnessProgressPhoto> {
  const form = new FormData();
  form.append("photo", photo);
  if (note) {
    form.append("note", note);
  }
  const response = await fetch(`${BASE_URL}/api/fitness/progress_photos`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Progress photo upload failed with status ${response.status}`);
  }
  return (await response.json()) as FitnessProgressPhoto;
}

export function getFitnessProgressPhotoFileUrl(photoId: number): string {
  return withTokenParam(`${BASE_URL}/api/fitness/progress_photos/${photoId}/file`);
}

export async function deleteFitnessProgressPhoto(photoId: number): Promise<void> {
  await requestJson(`/api/fitness/progress_photos/${photoId}`, { method: "DELETE" });
}

export async function sendFitnessChatMessage(text: string): Promise<string> {
  const response = await requestJson<{ reply: string }>("/api/fitness/chat", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  return response.reply;
}
