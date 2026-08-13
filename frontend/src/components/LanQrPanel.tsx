import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { getLanUrl } from "../api/client";
import { isElectron } from "../platform/electronAdapter";

// Desktop-only convenience: shows a QR code that opens this machine's LAN
// address on a phone's camera, so it can be used as a thin client (see
// core/main.py's static frontend mount + /api/voice/*). Pointless on the
// phone itself, so it only renders inside the Electron shell.
export function LanQrPanel(): JSX.Element | null {
  const [url, setUrl] = useState<string>("");
  const [qrDataUrl, setQrDataUrl] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!isElectron()) {
      return;
    }
    let cancelled = false;
    let attempt = 0;
    // This effect fires the moment the renderer's JS executes, which can
    // beat the backend's ~1-2s uvicorn+plugin startup (see
    // core.watchdog.supervisor) to the punch — see App.tsx's own
    // /api/status poll, which shrugs off the same race by retrying every
    // 1.5s forever. This effect used to run once and give up permanently
    // on that single early failure. Retry a bounded number of times
    // instead of forever, since a real (non-startup) failure should still
    // surface.
    const MAX_ATTEMPTS = 5;
    const RETRY_DELAY_MS = 1000;

    async function load(): Promise<void> {
      attempt += 1;
      try {
        const { url: lanUrl } = await getLanUrl();
        if (cancelled) {
          return;
        }
        setUrl(lanUrl);
        const dataUrl = await QRCode.toDataURL(lanUrl, { margin: 1, width: 160 });
        if (!cancelled) {
          setQrDataUrl(dataUrl);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (attempt < MAX_ATTEMPTS) {
          setTimeout(() => void load(), RETRY_DELAY_MS);
          return;
        }
        console.error("Failed to build the LAN QR code:", error);
        setError("Не удалось определить адрес в локальной сети.");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!isElectron()) {
    return null;
  }

  return (
    <div className="section lan-qr-panel">
      <h3>Подключить телефон</h3>
      {error && <p className="status-error">{error}</p>}
      {qrDataUrl && <img src={qrDataUrl} alt={`QR-код для ${url}`} width={160} height={160} />}
      {url && <p className="lan-url">{url}</p>}
    </div>
  );
}
