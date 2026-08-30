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
      <ul className="gesture-mode__legend">
        <li>
          <b>Рука перед камерой</b> — курсор (увеличен в 1,5×) идёт за указательным пальцем;
          работает по всему компьютеру. Активна центральная часть кадра.
        </li>
        <li>
          <b>Замедли руку у цели</b> — курсор переходит на точное наведение и замирает при
          наведении, чтобы попасть в мелкую кнопку.
        </li>
        <li>
          <b>Щипок</b> (большой + указательный, «ОК» / держишь монетку) — клик.
        </li>
        <li>
          <b>Щипок и веди</b> — выделение / перетаскивание. Разжал — отпустил.
        </li>
        <li>
          <b>Две руки в стороны / вместе</b> — масштаб (Ctrl + колесо).
        </li>
        <li>
          <b>Взмах открытой ладонью влево / вправо</b> — переключение окон (Alt+Tab).
        </li>
        <li>
          <b>Тронул физическую мышь</b> — жесты уступают на пару секунд, убрал руку — снова активны.
        </li>
      </ul>
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
