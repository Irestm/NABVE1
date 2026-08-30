import { app, BrowserWindow, desktopCapturer, dialog, ipcMain, session, shell } from "electron";
import { randomBytes } from "node:crypto";
import path from "node:path";
import { startBackend, stopBackend } from "./backend";
import { applyGestureOverlay, destroyGestureOverlay } from "./gestureOverlay";
import { getSetupLogPath, needsSetup, runSetup } from "./setup";
import { createSetupWindow, sendSetupError, sendSetupProgress } from "./setupWindow";
import { createTray, TrayHandle } from "./tray";
import { BACKEND_BASE_URL, DEV_SERVER_URL } from "./config";

// Electron's app.getPath("userData") (used by electron/setup.ts for the
// venv, and by backend.ts for ASSISTANT_DATA_DIR/ASSISTANT_LOGS_DIR) is
// keyed off this name — without setting it explicitly it falls back to
// package.json's "name" ("assistant-frontend"), which would put the venv
// and setup log somewhere the user can't recognize. Must run before
// anything else calls app.getPath("userData") — including
// requestSingleInstanceLock() right below, which resolves and caches a
// lock file under userData itself: calling it before setName() here was
// tried once and silently switched the whole app over to the
// "assistant-frontend" profile (fresh venv, fresh setup wizard) instead
// of the real "NABVE1" one.
app.setName("NABVE1");

// Must run as early as possible after that: a second click on the desktop
// icon (or any second launch) would otherwise spawn a duplicate Electron +
// watchdog + uvicorn tree that fights the first one for the hardcoded
// backend port (see core/config.py) and crash-loops instead of ever
// showing a window. requestSingleInstanceLock() makes every instance after
// the first quit immediately; the original process gets a "second-instance"
// event instead (registered below, once mainWindow exists) and just
// focuses its window.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
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
  let trayHandle: TrayHandle | null = null;
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

  // The renderer polls /api/status; when it sees gesture_mode_active it
  // asks main to show/size the transparent enlarged-cursor overlay — see
  // preload.ts's setGestureOverlay and frontend/src/App.tsx.
  ipcMain.on("gesture-overlay-changed", (_event, payload: { active?: boolean; scale?: number }) => {
    applyGestureOverlay(Boolean(payload?.active), Number(payload?.scale) || 1.3);
  });

  // components/CustomCommandsPanel.tsx's launch_app "Обзор…" button (see
  // preload.ts's pickExecutablePath) — the first invoke/handle (two-way,
  // promise-returning) IPC pair in this app; everything else here is
  // fire-and-forget ipcMain.on/send. No file-type filter: an "executable"
  // is platform-dependent (a .exe on Windows, no extension at all on
  // Linux, an .app bundle on macOS), so this just lets the user pick any
  // file/bundle rather than guessing a filter that would exclude valid
  // choices on some platform.
  ipcMain.handle("pick-executable", async () => {
    const options: Electron.OpenDialogOptions = { properties: ["openFile"] };
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options);
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
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
      // A distinct file from assets/icons/icon.png: that one is also the
      // electron-builder.yml win/linux `icon:` build resource, which
      // electron-builder silently excludes from the packaged app.asar even
      // though other assets/icons/*.png files (e.g. tray-idle.png) get
      // bundled normally — confirmed via `npx asar list` on a packaged
      // build. Runtime window icon needs its own untouched copy.
      icon: path.join(__dirname, "..", "assets", "icons", "window.png"),
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

  // Window is created with show: false to avoid a blank flash while
  // index.html loads. Resolves once the renderer has actually painted
  // content — used below alongside waitForBackendReady() so the first
  // reveal waits on both, not just this one.
  function waitForWindowPainted(window: BrowserWindow): Promise<void> {
    return new Promise((resolve) => {
      window.once("ready-to-show", () => resolve());
    });
  }

  const BACKEND_READY_POLL_INTERVAL_MS = 200;
  const BACKEND_READY_TIMEOUT_MS = 20000;

  // core/watchdog/supervisor.py spawns uvicorn and only then starts loading
  // modules/plugins (~1-2s before it accepts connections, per
  // ~/.config/NABVE1/logs/assistant.log) — startBackend() above only spawns
  // the process and returns immediately, it doesn't wait for any of that.
  // Without this gate, showing the window as soon as it's painted (which
  // happens fast — Vite's static bundle, no network round trip) reveals it
  // while the backend's port isn't listening yet, so App.tsx's first
  // /api/status poll(s) fail and the user sees "Нет связи с ядром
  // ассистента" for a second or two on every single launch even though
  // nothing is actually wrong. Bounded by a timeout so a genuinely broken
  // backend still shows the window (with the real, honest error) instead of
  // hanging forever.
  async function waitForBackendReady(): Promise<void> {
    const deadline = Date.now() + BACKEND_READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(`${BACKEND_BASE_URL}/api/status`, {
          headers: { "X-Assistant-Token": apiToken },
        });
        if (response.ok) {
          return;
        }
      } catch {
        // Not listening yet — retry until the deadline.
      }
      await new Promise((resolve) => setTimeout(resolve, BACKEND_READY_POLL_INTERVAL_MS));
    }
    // Falls through to showing the window anyway (see this function's own
    // comment above) — App.tsx's own /api/status poll will then surface
    // "Нет связи с ядром ассистента" to the user. This log line is only so
    // the reason is visible in the packaged app's own log file, not just
    // inferred from the frontend's generic connection error.
    process.stderr.write(`[main] Backend did not become ready within ${BACKEND_READY_TIMEOUT_MS}ms\n`);
  }

  // eslint-disable-next-line @typescript-eslint/no-inner-declarations
  function setAlwaysOnTop(enabled: boolean): void {
    mainWindow?.setAlwaysOnTop(enabled);
  }

  function startUiVisibilityPolling(): void {
    visibilityPollTimer = setInterval(() => {
      void fetch(`${BACKEND_BASE_URL}/api/ui/visibility_request`, {
        headers: { "X-Assistant-Token": apiToken },
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((raw: unknown) => {
          const body = raw as { action?: string | null } | null;
          if (!mainWindow || !body?.action) {
            return;
          }
          if (body.action === "show") {
            mainWindow.show();
            mainWindow.focus();
            trayHandle?.setHiddenIndicator(false);
          } else if (body.action === "hide") {
            mainWindow.hide();
            trayHandle?.setHiddenIndicator(true);
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
    trayHandle = createTray(mainWindow, setAlwaysOnTop);
    startUiVisibilityPolling();
    registerMeetingDisplayMediaHandler();

    const window = mainWindow;
    await Promise.all([waitForWindowPainted(window), waitForBackendReady()]);
    window.show();
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

  app
    .whenReady()
    .then(async () => {
      if (app.isPackaged && (await needsSetup())) {
        await runSetupFlow();
      } else {
        await launchNormally();
      }
    })
    .catch((error: unknown) => {
      // Without this .catch(), a failure here (including backend.ts's
      // startBackend spawn error) becomes an unhandled promise rejection —
      // no dialog, no window, the app just appears to do nothing.
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write(`[main] Fatal error during startup: ${message}\n`);
      dialog.showErrorBox("NABVE1 failed to start", message);
      app.quit();
    });

  // Fired on the original (first) instance when the user launches the icon
  // again while it's already running — bring the existing window forward
  // instead of letting a second process spawn and fight over the backend
  // port.
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.show();
      mainWindow.focus();
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
    trayHandle?.tray.destroy();
    destroyGestureOverlay();
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
}
