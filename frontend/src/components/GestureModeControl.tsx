import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Check, Eye, GraduationCap, Hand, X } from "lucide-react";
import { getStatus, gesturePreviewUrl, runCommand, setGesturePreview } from "../api/client";
import type { GestureCalibration } from "../types";
import { GestureTraining } from "./GestureTraining";
import "./GestureModeControl.css";

const POLL_INTERVAL_MS = 2000;
const POLL_INTERVAL_CALIBRATING_MS = 500;

interface GestureModeControlProps {
  accent: string;
}

// One entry in the "Режимы" group. Collapsed while the mode is off; once
// active it expands to the gesture legend + "Обучение"/"Выключить". The
// "Обучение" button opens the full-screen GestureTraining game, which also
// runs the calibration session underneath.
export function GestureModeControl({ accent }: GestureModeControlProps): JSX.Element {
  const [active, setActive] = useState(false);
  const [calibration, setCalibration] = useState<GestureCalibration | null>(null);
  const [training, setTraining] = useState(false);
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

      {calibration && !training ? (
        <div className="gesture-cal">
          <div className="gesture-cal__step">
            Обучение {Math.min(calibration.phase_index, calibration.total_phases)} из{" "}
            {calibration.total_phases}: <b>{calibration.label}</b>
          </div>
          <p className="gesture-cal__instruction">
            {calibration.done
              ? "Обучение пройдено — жесты подстроены под вас."
              : `${calibration.instruction}. Следите за кружками.`}
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
            <b>Указательный палец вытянут</b> — наводишь его кончиком, курсор (крупнее в 1,5×)
            становится в ту же точку экрана. Указал на угол кадра — курсор в углу.
          </li>
          <li>
            <b>Указательный и средний вытянуты вместе</b> (знак «V») — курсор замирает, движение
            кисти вверх/вниз крутит колесо: <b>скролл страницы</b>. Палец вверх — страница вверх.
          </li>
          <li>
            <b>Сжал руку в кулак</b> (все пальцы, кроме большого) — левый клик там, где стоял
            курсор (пока сжимаешь, указательный опускается и курсор сам замирает). Держишь
            кулак и ведёшь рукой — перетаскивание. Разжал — отпустил.
          </li>
          <li>
            <b>Кулак + большой палец в сторону</b> (👍) — правый клик.
          </li>
          <li>
            <b>Раскрытая ладонь</b> (все пальцы врозь, большой в сторону) — «ничего не делаю».
            Система тебя видит, но курсор стоит, клик и скролл не срабатывают — так спокойно
            переставляешь руку в удобное место между жестами.
          </li>
          <li>
            <b>Убрал указательный / опустил руку / кулак</b> — курсор тоже замирает (клатч).
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
        {calibration && !calibration.done && !training ? (
          <button
            type="button"
            className="gesture-mode__action"
            disabled={busy}
            onClick={() => void run("gesture_calibrate_cancel")}
          >
            <X size={15} />
            Отменить обучение
          </button>
        ) : (
          <button
            type="button"
            className="gesture-mode__action"
            disabled={busy || training}
            onClick={() => {
              setTraining(true);
              void run("gesture_calibrate");
            }}
          >
            <GraduationCap size={15} />
            Обучение
          </button>
        )}
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

      {training ? (
        <GestureTraining
          calibration={calibration}
          onCancelBackend={() => void run("gesture_calibrate_cancel")}
          onFinished={() => void runCommand("gesture_training_done").catch(() => undefined)}
          onExit={() => {
            setTraining(false);
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
}
