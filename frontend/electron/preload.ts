import { contextBridge, ipcRenderer } from "electron";

// Deliberately not `import { BACKEND_BASE_URL } from "./config"` (as main.ts
// does) — this script runs through Electron's sandboxed preload loader
// (the default since webPreferences.sandbox isn't set to false), which only
// resolves a small built-in allowlist ("electron", node builtins, ...) and
// throws "module not found" for any require() of a sibling compiled file,
// silently killing the whole preload script before it ever reaches
// contextBridge.exposeInMainWorld below — confirmed via the renderer's
// devtools console, which is the only place Electron surfaces that error
// (it never reaches main-process stdout/stderr). Every consumer of
// window.assistantAPI then sees it as simply undefined, with no error of
// its own. Keep this in sync with electron/config.ts's BACKEND_BASE_URL by
// hand until preload has a real bundler step.
const BACKEND_BASE_URL = "http://127.0.0.1:8756";

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
  // components/CustomCommandsPanel.tsx's launch_app "Обзор…" button — see
  // main.ts's ipcMain.handle("pick-executable", ...). Two-way/promise-
  // returning (invoke, not send) since the renderer needs the chosen path
  // back, unlike setRecordingActive above.
  pickExecutablePath: () => ipcRenderer.invoke("pick-executable") as Promise<string | null>,
  // frontend/src/App.tsx calls this on every /api/status poll so main.ts
  // can show/size the transparent enlarged-cursor overlay while
  // modules/gesture_control is active.
  setGestureOverlay: (active: boolean, scale: number) => {
    ipcRenderer.send("gesture-overlay-changed", { active, scale });
  },
});
