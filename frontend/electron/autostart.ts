import { app, ipcMain } from "electron";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

const DESKTOP_FILE_NAME = "nabve1.desktop";

function linuxAutostartPath(): string {
  const configHome = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(configHome, "autostart", DESKTOP_FILE_NAME);
}

function quoteExecArgument(value: string): string {
  const escaped = value
    .replace(/\\/g, "\\\\\\\\")
    .replace(/["`$]/g, (match: string) => `\\\\${match}`)
    .replace(/%/g, "%%");
  return `"${escaped}"`;
}

function launchCommand(): string {
  if (process.env.APPIMAGE) {
    return quoteExecArgument(process.env.APPIMAGE);
  }
  const parts: string[] = [process.execPath];
  if (!app.isPackaged) {
    parts.push(app.getAppPath());
  }
  return parts.map(quoteExecArgument).join(" ");
}

function desktopEntry(): string {
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Name=NABVE1",
    "Comment=Neural Assistant",
    `Exec=${launchCommand()}`,
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    "",
  ].join("\n");
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

export async function getAutostart(): Promise<boolean> {
  if (process.platform === "linux") {
    return fileExists(linuxAutostartPath());
  }
  return app.getLoginItemSettings().openAtLogin;
}

export async function setAutostart(enabled: boolean): Promise<boolean> {
  if (process.platform === "linux") {
    const filePath = linuxAutostartPath();
    if (enabled) {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, desktopEntry(), { encoding: "utf-8", mode: 0o644 });
    } else {
      await fs.rm(filePath, { force: true });
    }
    return getAutostart();
  }
  app.setLoginItemSettings({ openAtLogin: enabled });
  return getAutostart();
}

export function registerAutostartIpc(): void {
  ipcMain.handle("autostart-get", () => getAutostart());
  ipcMain.handle("autostart-set", (_event: Electron.IpcMainInvokeEvent, enabled: unknown) =>
    setAutostart(Boolean(enabled)),
  );
}
