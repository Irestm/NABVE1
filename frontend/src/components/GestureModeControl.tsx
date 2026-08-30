import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Check, Crosshair, Eye, Hand, X } from "lucide-react";
import { getStatus, gesturePreviewUrl, runCommand, setGesturePreview } from "../api/client";
import type { GestureCalibration } from "../types";
import "./GestureModeControl.css";

const POLL_INTERVAL_MS = 2000;
const POLL_INTERVAL_CALIBRATING_MS = 500;

interface GestureModeControlProps {
  accent: string;
}

// One entry in the "Режимы" group. Collapsed while the mode is off; once
// active it expands to the gesture legend + "Калибровка"/"Выключить", and
// while the calibration wizard runs it shows the step-by-step progress.
export function GestureModeControl({ accent }: GestureModeControlProps): JSX.Element {
  const [active, setActive] = useState(false);
  const [calibration, setCalibration] = useState<GestureCalibration | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const [previewSrc, setPreviewSrc] = useState("");
  const busyRef = useRef(false);
  const calibratingRef = useRef(false);

  async function refresh(): Promise<void> {
    try {
      const status = await getStatus();
      setActive(status.gesture_mode_active);
      setCalibration(status.gesture_calibration ?? null);
      calibratingRef.current = Boolean(status.gesture_calibration);
    } catch (err) {
      console.error("GestureModeControl status poll failed:", err);
    }
  }

  useEffect(() => {
    void refresh();
    let timer = 0;
    const tick = () => {
      if (!busyRef.current) void refresh();
      timer = window.setTimeout(
        tick,
        calibratingRef.current ? POLL_INTERVAL_CALIBRATING_MS : POLL_INTERVAL_MS,
      );
    };
    timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, []);

  // Turn the backend preview producer on only while the checkbox is on and
  // the mode is active; poll the JPEG a few times a second.
  useEffect(() => {
    const on = preview && active;
    void setGesturePreview(on).catch(() => undefined);
    if (!on) {
      setPreviewSrc("");
      return;
    }
    const timer = window.setInterval(() => setPreviewSrc(gesturePreviewUrl()), 150);
    return () => {
      window.clearInterval(timer);
      void setGesturePreview(false).catch(() => undefined);
    };
  }, [preview, active]);

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

      {calibration ? (
        <div className="gesture-cal">
          <div className="gesture-cal__step">
            Калибровка {Math.min(calibration.phase_index, calibration.total_phases)} из{" "}
            {calibration.total_phases}: <b>{calibration.label}</b>
          </div>
          <p className="gesture-cal__instruction">
            {calibration.done
              ? "Калибровка завершена — жесты подстроены под вас."
              : `${calibration.instruction}. Повторите ${calibration.reps_target} раз — следите за кружками.`}
          </p>
          <div className="gesture-cal__dots">
            {Array.from({ length: calibration.reps_target }).map((_, i) => (
              <span
                key={i}
                className={
                  "gesture-cal__dot" + (i < calibration.reps_done ? " gesture-cal__dot--on" : "")
                }
              >
                {i < calibration.reps_done ? <Check size={12} strokeWidth={3} /> : null}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <ul className="gesture-mode__legend">
          <li>
            <b>Рука перед камерой</b> — курсор (увеличен в 1,5×) идёт за центром ладони; работает
            по всему компьютеру. Активна центральная часть кадра.
          </li>
          <li>
            <b>Сожми руку в кулак</b> — клик. Не разжимая, веди — выделение / перетаскивание.
            Разжал — отпустил.
          </li>
          <li>
            <b>Взмах открытой ладонью влево / вправо</b> — переключение окон (Alt+Tab).
          </li>
          <li>
            <b>Две руки в стороны / вместе</b> — масштаб (Ctrl + колесо).
          </li>
          <li>
            <b>Тронул физическую мышь</b> — жесты уступают на пару секунд, убрал руку — снова
            активны.
          </li>
        </ul>
      )}

      <button
        type="button"
        className={"gesture-mode__action" + (preview ? " gesture-mode__action--on" : "")}
        onClick={() => setPreview((v) => !v)}
      >
        <Eye size={15} />
        {preview ? "Скрыть превью камеры" : "Показать превью камеры"}
      </button>
      {preview && previewSrc ? (
        <img className="gesture-mode__preview" src={previewSrc} alt="Превью камеры с landmarks" />
      ) : null}

      <div className="gesture-mode__actions">
        <button
          type="button"
          className="gesture-mode__action"
          disabled={busy || Boolean(calibration && !calibration.done)}
          onClick={() => void run("gesture_calibrate")}
        >
          <Crosshair size={15} />
          {calibration && !calibration.done ? "Калибровка…" : "Калибровка"}
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
