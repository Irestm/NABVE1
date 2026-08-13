import type {
  AIBridgeStatus,
  CalendarEvent,
  CommandDescriptor,
  CommandResponse,
  CommunicationStyle,
  ImageRequest,
  LanUrlResponse,
  MeetingRecording,
  PluginSuggestion,
  SpeakResponse,
  StatusResponse,
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
): Promise<CommandResponse> {
  return runCommand("calendar_create_event", {
    title,
    event_time: eventTimeIso,
    remind_before_minutes: remindBeforeMinutes,
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
