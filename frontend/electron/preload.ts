import { contextBridge, ipcRenderer } from "electron";
import { BACKEND_BASE_URL } from "./config";

const API_TOKEN_ARG_PREFIX = "--api-token=";

// main.ts passes the generated token via this window's additionalArguments
// (see createStatusWindow) rather than contextBridge directly, since the
// token is generated after app startup but before this preload script
// runs — process.argv is the one channel both ends can rely on without
// extra IPC round-trips before the page has even loaded.
function readApiToken(): string {
  const arg = process.argv.find((value) => value.startsWith(API_TOKEN_ARG_PREFIX));
  return arg ? arg.slice(API_TOKEN_ARG_PREFIX.length) : "";
}

contextBridge.exposeInMainWorld("assistantAPI", {
  backendBaseUrl: BACKEND_BASE_URL,
  apiToken: readApiToken(),
  // Lets main.ts gate window-close/app-quit behind a confirmation dialog
  // only while a meeting recording is actually in progress — see
  // frontend/src/meeting/meetingRecorder.ts (calls this on every state
  // transition) and main.ts's "before-quit" handler.
  setRecordingActive: (active: boolean) => {
    ipcRenderer.send("meeting-recording-active-changed", active);
  },
});
