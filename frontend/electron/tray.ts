import { app, BrowserWindow, Menu, Tray } from "electron";
import path from "node:path";

export function createTray(window: BrowserWindow, setAlwaysOnTop: (enabled: boolean) => void): Tray {
  const iconPath = path.join(__dirname, "..", "assets", "icons", "tray-idle.png");
  const tray = new Tray(iconPath);
  tray.setToolTip("Jarvis");

  let alwaysOnTop = false;

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Показать окно",
      click: () => {
        window.show();
        window.focus();
      },
    },
    {
      label: "Скрыть окно",
      click: () => {
        window.hide();
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
    } else {
      window.show();
      window.focus();
    }
  });

  return tray;
}
