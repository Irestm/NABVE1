import { contextBridge, ipcRenderer } from "electron";
import type { SetupProgress } from "./setup";

// Deliberately its own tiny bridge, separate from preload.ts's
// `assistantAPI` — this window never talks to the backend (there isn't one
// running yet during setup), it only reflects setupWindow.ts's own IPC
// messages sent from main.ts's setup-orchestration flow.
contextBridge.exposeInMainWorld("setupAPI", {
  onProgress: (callback: (progress: SetupProgress) => void) => {
    ipcRenderer.on("setup-progress", (_event, progress: SetupProgress) => callback(progress));
  },
  onError: (callback: (message: string) => void) => {
    ipcRenderer.on("setup-error", (_event, message: string) => callback(message));
  },
  retry: () => ipcRenderer.send("setup-retry"),
  openLog: () => ipcRenderer.send("setup-open-log"),
});
