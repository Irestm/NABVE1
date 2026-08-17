import { app, BrowserWindow, Menu, Tray } from "electron";
import path from "node:path";

export interface TrayHandle {
  tray: Tray;
  // Swaps the tray icon between its normal and "muted" (tray-hidden.png,
  // a dimmed version of tray-idle.png) look — called both from this
  // module's own click handler and from main.ts's visibility-polling
  // handler (see startUiVisibilityPolling), which is the only place that
  // learns about a voice-triggered show/hide (modules/tray_hide) since the
  // backend has no direct handle to this Tray instance.
  setHiddenIndicator: (hidden: boolean) => void;
}

const ICONS_DIR = path.join(__dirname, "..", "assets", "icons");

export function createTray(window: BrowserWindow, setAlwaysOnTop: (enabled: boolean) => void): TrayHandle {
  const idleIconPath = path.join(ICONS_DIR, "tray-idle.png");
  const hiddenIconPath = path.join(ICONS_DIR, "tray-hidden.png");
  const tray = new Tray(idleIconPath);
  tray.setToolTip("Jarvis");

  function setHiddenIndicator(hidden: boolean): void {
    tray.setImage(hidden ? hiddenIconPath : idleIconPath);
  }

  let alwaysOnTop = false;

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Показать окно",
      click: () => {
        window.show();
        window.focus();
        setHiddenIndicator(false);
      },
    },
    {
      label: "Скрыть окно",
      click: () => {
        window.hide();
        setHiddenIndicator(true);
      },
    },
    { type: "separator" },
    {
      label: "Поверх всех окон",
      type: "checkbox",
      checked: alwaysOnTop,
      click: (menuItem) => {
        alwaysOnTop = menuItem.checked;
        setAlwaysOnTop(alwaysOnTop);
      },
    },
    { type: "separator" },
    {
      label: "Выход",
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on("click", () => {
    if (window.isVisible()) {
      window.hide();
      setHiddenIndicator(true);
    } else {
      window.show();
      window.focus();
      setHiddenIndicator(false);
    }
  });

  return { tray, setHiddenIndicator };
}
