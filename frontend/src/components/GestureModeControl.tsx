import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Crosshair, Hand, X } from "lucide-react";
import { getStatus, runCommand } from "../api/client";
import "./GestureModeControl.css";

const POLL_INTERVAL_MS = 2000;

interface GestureModeControlProps {
  accent: string;
}

// One entry in the "Режимы" group that stands in for what used to be three
// separate buttons. Collapsed while the mode is off (a plain "Режим жестов"
// activator); once active it expands to reveal "Выключить" and "Калибровка".
export function GestureModeControl({ accent }: GestureModeControlProps): JSX.Element {
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function refresh(): Promise<void> {
    try {
      const status = await getStatus();
      setActive(status.gesture_mode_active);
    } catch (err) {
      console.error("GestureModeControl status poll failed:", err);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!busyRef.current) void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function run(command: string): Promise<void> {
    setBusy(true);
    busyRef.current = true;
    try {
      await runCommand(command);
    } catch (err) {
      console.error(`GestureModeControl: ${command} failed:`, err);
    } finally {
      setBusy(false);
      busyRef.current = false;
      await refresh();
    }
  }

  const style = { "--item-accent": accent } as CSSProperties;

  if (!active) {
    return (
      <button
        type="button"
        className="command-panel__button gesture-mode__activator"
        style={style}
        disabled={busy}
        onClick={() => void run("gesture_start")}
        title="Управление курсором жестами через веб-камеру"
      >
        <Hand size={22} />
        <span>Режим жестов</span>
      </button>
    );
  }

  return (
    <div className="gesture-mode" style={style}>
      <div className="gesture-mode__header">
        <Hand size={18} />
        <span className="gesture-mode__title">Режим жестов</span>
        <span className="gesture-mode__badge">активен</span>
      </div>
      <p className="gesture-mode__how">
        Поднесите руку к камере — курсор увеличится в 2 раза и пойдёт за ней. Щипок большого и
        указательного — клик и перетаскивание. Две руки в стороны/вместе — масштаб. Возьмётесь за
        физическую мышь — жесты уступают, вернёте руку — снова активны.
      </p>
      <div className="gesture-mode__actions">
        <button
          type="button"
          className="gesture-mode__action"
          disabled={busy}
          onClick={() => void run("gesture_calibrate")}
        >
          <Crosshair size={15} />
          Калибровка
        </button>
        <button
          type="button"
          className="gesture-mode__action gesture-mode__action--stop"
          disabled={busy}
          onClick={() => void run("gesture_stop")}
        >
          <X size={15} />
          Выключить
        </button>
      </div>
    </div>
  );
}
