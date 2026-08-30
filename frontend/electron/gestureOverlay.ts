import { BrowserWindow, screen } from "electron";
import path from "node:path";

// The enlarged cursor for modules/gesture_control is a tiny, transparent,
// click-through, always-on-top window that simply *follows* the real OS
// cursor — main moves it every frame with setPosition(). No renderer IPC
// needed: the window content is a static drawn cursor, and it never takes
// input (setIgnoreMouseEvents), so the actual click still lands on whatever
// is underneath. The Python side (cursor_controller) moves the real cursor;
// this only makes it visually bigger while the mode is on.

const BASE_SIZE = 34; // px of the drawn cursor at scale 1.0
const FOLLOW_INTERVAL_MS = 16; // ~60 Hz

let overlayWindow: BrowserWindow | null = null;
let followTimer: NodeJS.Timeout | null = null;
let currentScale = 1.3;

function overlayHtmlPath(): string {
  // Same shape as setupWindow.ts: compiled JS lives in dist-electron/, the
  // static .html stays in the source electron/ dir and is referenced back
  // up through it (electron-builder keeps electron/ in the asar).
  return path.join(__dirname, "..", "electron", "gesture-overlay.html");
}

function ensureWindow(): BrowserWindow {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    return overlayWindow;
  }
  const size = Math.round(BASE_SIZE * currentScale);
  overlayWindow = new BrowserWindow({
    width: size,
    height: size,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    focusable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    fullscreenable: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  void overlayWindow.loadFile(overlayHtmlPath());
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
  return overlayWindow;
}

function startFollowing(): void {
  if (followTimer) {
    return;
  }
  followTimer = setInterval(() => {
    if (!overlayWindow || overlayWindow.isDestroyed()) {
      return;
    }
    const point = screen.getCursorScreenPoint();
    const half = Math.round((BASE_SIZE * currentScale) / 2);
    overlayWindow.setPosition(point.x - half, point.y - half);
  }, FOLLOW_INTERVAL_MS);
}

function stopFollowing(): void {
  if (followTimer) {
    clearInterval(followTimer);
    followTimer = null;
  }
}

function applyScale(scale: number): void {
  currentScale = Math.max(1.0, Math.min(2.5, scale || 1.3));
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    const size = Math.round(BASE_SIZE * currentScale);
    overlayWindow.setSize(size, size);
  }
}

export function applyGestureOverlay(active: boolean, scale: number): void {
  applyScale(scale);
  if (active) {
    const win = ensureWindow();
    win.showInactive();
    startFollowing();
  } else {
    stopFollowing();
    if (overlayWindow && !overlayWindow.isDestroyed()) {
      overlayWindow.hide();
    }
  }
}

export function destroyGestureOverlay(): void {
  stopFollowing();
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.destroy();
  }
  overlayWindow = null;
}
