import { app, BrowserWindow, Tray, desktopCapturer, dialog, ipcMain, session, shell } from "electron";
import { randomBytes } from "node:crypto";
import path from "node:path";
import { startBackend, stopBackend } from "./backend";
import { getSetupLogPath, needsSetup, runSetup } from "./setup";
import { createSetupWindow, sendSetupError, sendSetupProgress } from "./setupWindow";
import { createTray } from "./tray";
import { BACKEND_BASE_URL, DEV_SERVER_URL } from "./config";

// Electron's app.getPath("userData") (used by electron/setup.ts for the
// venv, and by backend.ts for ASSISTANT_DATA_DIR/ASSISTANT_LOGS_DIR) is
// keyed off this name — without setting it explicitly it falls back to
// package.json's "name" ("assistant-frontend"), which would put the venv
// and setup log somewhere the user can't recognize. Must run before
// anything else calls app.getPath("userData").
app.setName("NABVE1");

const isDev = !app.isPackaged;

// Shared secret for every /api/* request — see core/main.py's
// require_api_token middleware. Generated fresh per app launch (unlike the
// backend's own persisted data/api_token.txt, this process always spawns
// its own backend right below with this exact value passed as
// ASSISTANT_API_TOKEN, so there's nothing to keep in sync across restarts)
// and handed to the renderer via preload.ts, which reads it back out of
// this window's additionalArguments — contextBridge itself can't carry a
// value generated after the BrowserWindow already exists.
const apiToken = randomBytes(32).toString("hex");
process.env.ASSISTANT_API_TOKEN = apiToken;

// Compact by default; resizable so the user can grow it, but never smaller
// than the minimum that keeps the orb/waveform/status panel legible.
const DEFAULT_WINDOW_WIDTH = 360;
const DEFAULT_WINDOW_HEIGHT = 560;
const MIN_WINDOW_WIDTH = 300;
const MIN_WINDOW_HEIGHT = 420;
const UI_VISIBILITY_POLL_INTERVAL_MS = 1000;

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let visibilityPollTimer: NodeJS.Timeout | null = null;
let isQuitting = false;
// Set via the "meeting-recording-active-changed" IPC message the preload
// bridge's assistantAPI.setRecordingActive() sends — see preload.ts. Only
// gates actual app quit (below); hiding the window to the tray already
// leaves a recording running untouched, so it needs no extra protection.
let meetingRecordingActive = false;

ipcMain.on("meeting-recording-active-changed", (_event, active: boolean) => {
  meetingRecordingActive = Boolean(active);
});

function confirmQuitDuringActiveRecording(): boolean {
  const options: Electron.MessageBoxSyncOptions = {
    type: "warning",
    buttons: ["Отмена", "Всё равно закрыть"],
    defaultId: 0,
    cancelId: 0,
    title: "Идёт запись встречи",
    message:
      "Сейчас записывается встреча. Если закрыть приложение сейчас, несохранённая часть записи будет потеряна.",
  };
  const choice = mainWindow
    ? dialog.showMessageBoxSync(mainWindow, options)
    : dialog.showMessageBoxSync(options);
  return choice === 1;
}

async function confirmScreenAndAudioCapture(): Promise<boolean> {
  const options: Electron.MessageBoxOptions = {
    type: "question",
    buttons: ["Отмена", "Разрешить"],
    defaultId: 1,
    cancelId: 0,
    title: "Захват экрана и звука встречи",
    message:
      "Приложение запрашивает захват окна/экрана и системного звука для записи встречи. " +
      "Сохраняется только звук — изображение никуда не записывается и не передаётся. Разрешить?",
  };
  const { response } = mainWindow
    ? await dialog.showMessageBox(mainWindow, options)
    : await dialog.showMessageBox(options);
  return response === 1;
}

function registerMeetingDisplayMediaHandler(): void {
  // First use of desktopCapturer/setDisplayMediaRequestHandler in this
  // codebase — without registering a handler, the renderer's
  // getDisplayMedia() call (see frontend/src/meeting/meetingRecorder.ts)
  // would simply reject inside Electron, unlike in a plain browser.
  //
  // `useSystemPicker: true` (Electron 32+) hands source selection to the
  // OS's own native picker, letting the user scope capture to one specific
  // meeting window/tab instead of blindly grabbing a source — this is
  // currently macOS 15+ only and still marked experimental by Electron
  // ("If the system picker is available ... the handler will not be
  // invoked" — Electron docs), so confirmScreenAndAudioCapture() below
  // never even runs there; the OS's own picker is the consent step on that
  // platform. Everywhere else (Linux, older macOS, Windows), this handler
  // is what actually runs, and — since setDisplayMediaRequestHandler has no
  // built-in per-request consent UI of its own outside the OS-picker path —
  // it must ask explicitly before granting anything: without that dialog,
  // ANY renderer code calling getDisplayMedia() (not just this module's own
  // capture flow) would silently receive screen + system-audio capture with
  // no prompt at all. It still just grabs the first available window/screen
  // source rather than letting the user pick a specific one, since that
  // picker UI is designed separately — revisit once `useSystemPicker`
  // broadens past macOS, or once this module's own UI adds a real source
  // list from desktopCapturer.
  session.defaultSession.setDisplayMediaRequestHandler(
    (_request, callback) => {
      void (async () => {
        const allowed = await confirmScreenAndAudioCapture();
        if (!allowed) {
          callback({});
          return;
        }
        try {
          const sources = await desktopCapturer.getSources({ types: ["window", "screen"] });
          callback(sources.length > 0 ? { video: sources[0], audio: "loopback" } : {});
        } catch (error) {
          console.error("desktopCapturer.getSources failed:", error);
          callback({});
        }
      })();
    },
    { useSystemPicker: true },
  );
}

function createStatusWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: DEFAULT_WINDOW_WIDTH,
    height: DEFAULT_WINDOW_HEIGHT,
    minWidth: MIN_WINDOW_WIDTH,
    minHeight: MIN_WINDOW_HEIGHT,
    resizable: true,
    fullscreenable: false,
    skipTaskbar: true,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#0d1117",
    icon: path.join(__dirname, "..", "assets", "icons", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // Chromium throttles timers in a hidden/minimized-to-tray renderer by
      // default, which would otherwise stutter or stall MediaRecorder's
      // periodic `ondataavailable` callback (see
      // frontend/src/meeting/meetingRecorder.ts) — a meeting recording must
      // keep running uninterrupted while this window is hidden in the tray.
      backgroundThrottling: false,
      // How preload.ts learns `apiToken` (see its own comment) — Electron
      // appends these verbatim to the renderer process's argv, which a
      // preload script (unlike the sandboxed renderer itself) can read.
      additionalArguments: [`--api-token=${apiToken}`],
    },
  });

  if (isDev) {
    void window.loadURL(DEV_SERVER_URL);
  } else {
    void window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  window.on("close", (event: Electron.Event) => {
    if (!isQuitting) {
      event.preventDefault();
      window.hide();
    }
  });

  return window;
}

export function setAlwaysOnTop(enabled: boolean): void {
  mainWindow?.setAlwaysOnTop(enabled);
}

function startUiVisibilityPolling(): void {
  visibilityPollTimer = setInterval(() => {
    void fetch(`${BACKEND_BASE_URL}/api/ui/visibility_request`)
      .then((response) => (response.ok ? response.json() : null))
      .then((raw: unknown) => {
        const body = raw as { action?: string | null } | null;
        if (!mainWindow || !body?.action) {
          return;
        }
        if (body.action === "show") {
          mainWindow.show();
          mainWindow.focus();
        } else if (body.action === "hide") {
          mainWindow.hide();
        }
      })
      .catch(() => {
        // Backend not up yet (or briefly unreachable) — just retry next tick.
      });
  }, UI_VISIBILITY_POLL_INTERVAL_MS);
}

async function launchNormally(): Promise<void> {
  await startBackend();
  mainWindow = createStatusWindow();
  tray = createTray(mainWindow, setAlwaysOnTop);
  startUiVisibilityPolling();
  registerMeetingDisplayMediaHandler();
}

// Only ever runs for a packaged build on its first launch (or after
// electron/setup.ts's SETUP_SCHEMA_VERSION is bumped for an existing
// install) — `npm run dev`/`dev:docker` always skip straight to
// launchNormally(), so this never affects the developer workflow.
async function runSetupFlow(): Promise<void> {
  const setupWindow = createSetupWindow();

  async function attempt(): Promise<void> {
    try {
      await runSetup((progress) => sendSetupProgress(setupWindow, progress));
      // launchNormally() must create the real status window BEFORE the
      // setup window closes — closing it first would briefly leave zero
      // windows open, which fires Electron's "window-all-closed" handler
      // (below) and quits the whole app before the status window ever gets
      // created. Confirmed as a real bug in manual testing, not a
      // hypothetical one.
      await launchNormally();
      setupWindow.close();
    } catch (error) {
      sendSetupError(setupWindow, error instanceof Error ? error.message : String(error));
    }
  }

  ipcMain.on("setup-retry", () => void attempt());
  ipcMain.on("setup-open-log", () => void shell.openPath(getSetupLogPath()));

  await attempt();
}

app.whenReady().then(async () => {
  if (app.isPackaged && (await needsSetup())) {
    await runSetupFlow();
  } else {
    await launchNormally();
  }
});

app.on("before-quit", (event) => {
  if (!isQuitting && meetingRecordingActive && !confirmQuitDuringActiveRecording()) {
    event.preventDefault();
    return;
  }
  isQuitting = true;
  if (visibilityPollTimer) {
    clearInterval(visibilityPollTimer);
    visibilityPollTimer = null;
  }
  tray?.destroy();
  stopBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (mainWindow) {
    mainWindow.show();
  }
});
