import { BrowserWindow } from "electron";
import path from "node:path";
import type { SetupProgress } from "./setup";

const WINDOW_WIDTH = 380;
const WINDOW_HEIGHT = 220;

export function createSetupWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    resizable: false,
    fullscreenable: false,
    skipTaskbar: false,
    autoHideMenuBar: true,
    backgroundColor: "#0d1117",
    title: "NABVE1 — первый запуск",
    webPreferences: {
      preload: path.join(__dirname, "setup-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  void window.loadFile(path.join(__dirname, "..", "electron", "setup-ui", "index.html"));
  return window;
}

export function sendSetupProgress(window: BrowserWindow, progress: SetupProgress): void {
  if (!window.isDestroyed()) {
    window.webContents.send("setup-progress", progress);
  }
}

export function sendSetupError(window: BrowserWindow, message: string): void {
  if (!window.isDestroyed()) {
    window.webContents.send("setup-error", message);
  }
}
