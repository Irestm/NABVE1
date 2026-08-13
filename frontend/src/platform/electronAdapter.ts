// The only place shared components should check whether they're running
// inside the Electron shell vs. a plain browser (desktop dev, or a phone
// connecting over the LAN as a thin client). Electron's preload script is the
// one thing a normal browser can never provide, so its presence is a safe,
// synchronous signal — no user agent sniffing.
//
// Components like StatusWindow/PluginSuggestions never call Electron APIs
// directly: they only talk to the backend over HTTP via ../api/client. Any
// future Electron-only action (native dialogs, tray/window control, etc.)
// should be gated through `isElectron()` here and hidden/no-op otherwise,
// so the exact same component tree renders correctly on a phone's browser.
export function isElectron(): boolean {
  return typeof window !== "undefined" && window.assistantAPI !== undefined;
}
