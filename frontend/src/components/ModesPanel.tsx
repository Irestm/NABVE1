import { useEffect, useRef, useState } from "react";
import { Hand, MessagesSquare } from "lucide-react";
import {
  calibrateGestures,
  getStatus,
  gesturePreviewUrl,
  runCommand,
  setGestureCursorScale,
  startGestureMode,
  stopGestureMode,
} from "../api/client";
import { GestureInstructions } from "./GestureInstructions";
import "./ModesPanel.css";

const POLL_INTERVAL_MS = 2000;

export function ModesPanel(): JSX.Element {
  const [gestureActive, setGestureActive] = useState(false);
  const [cursorScale, setCursorScale] = useState(1.3);
  const [showInstructions, setShowInstructions] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const busyRef = useRef(false);

  async function refresh(): Promise<void> {
    try {
      const status = await getStatus();
      setGestureActive(status.gesture_mode_active);
      setCursorScale(status.gesture_cursor_scale);
    } catch (err) {
      console.error("Failed to poll status for ModesPanel:", err);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!busyRef.current) {
        void refresh();
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function toggleGesture(): Promise<void> {
    setBusy(true);
    busyRef.current = true;
    try {
      const response = gestureActive ? await stopGestureMode() : await startGestureMode();
      setMessage(response.message ?? "");
      if (!gestureActive && !showInstructions) {
        // First visible entry — surface the how-to.
        setShowInstructions(true);
      }
    } catch (err) {
      console.error("Gesture toggle failed:", err);
      setMessage("Не удалось переключить режим жестов.");
    } finally {
      setBusy(false);
      busyRef.current = false;
      await refresh();
    }
  }

  async function recalibrate(): Promise<void> {
    try {
      const response = await calibrateGestures();
      setMessage(response.message ?? "");
    } catch (err) {
      console.error("Recalibrate failed:", err);
      setMessage("Калибровка доступна только при активном режиме жестов.");
    }
  }

  async function onScaleCommit(value: number): Promise<void> {
    setCursorScale(value);
    try {
      await setGestureCursorScale(value);
    } catch (err) {
      console.error("Set cursor scale failed:", err);
    }
  }

  async function startDiscussion(): Promise<void> {
    try {
      const response = await runCommand("discussion_start");
      setMessage(response.message ?? "");
    } catch (err) {
      console.error("Discussion start failed:", err);
      setMessage("Не удалось включить режим дискуссии.");
    }
  }

  return (
    <div className="modes-panel">
      <p className="modes-panel__lead">
        Переключаемые специальные режимы. Ресурсоёмкие — включаются явно и работают, пока не выключишь.
      </p>

      <div className={`modes-card${gestureActive ? " modes-card--active" : ""}`}>
        <div className="modes-card__head">
          <span className="modes-card__icon">
            <Hand size={20} />
          </span>
          <div className="modes-card__title-wrap">
            <span className="modes-card__title">Управление жестами</span>
            <span className={`modes-card__status${gestureActive ? " modes-card__status--on" : ""}`}>
              {gestureActive ? "Включено" : "Выключено"}
            </span>
          </div>
          <button
            type="button"
            className={`modes-card__toggle${gestureActive ? " modes-card__toggle--on" : ""}`}
            onClick={() => void toggleGesture()}
            disabled={busy}
          >
            {busy ? "…" : gestureActive ? "Выключить" : "Включить"}
          </button>
        </div>

        <p className="modes-card__hint">
          Курсор системы следует за рукой через веб-камеру. Голосовые команды продолжают работать.
        </p>

        <div className="modes-card__row">
          <button type="button" className="modes-card__btn" onClick={() => setShowInstructions(true)}>
            Инструкция
          </button>
          <button
            type="button"
            className="modes-card__btn"
            onClick={() => void recalibrate()}
            disabled={!gestureActive}
          >
            Перекалибровать
          </button>
        </div>

        <label className="modes-card__slider">
          <span>Размер курсора: {Math.round(cursorScale * 100)}%</span>
          <input
            type="range"
            min={1}
            max={2.5}
            step={0.1}
            value={cursorScale}
            onChange={(event) => setCursorScale(Number(event.target.value))}
            onMouseUp={(event) => void onScaleCommit(Number((event.target as HTMLInputElement).value))}
            onTouchEnd={(event) => void onScaleCommit(Number((event.target as HTMLInputElement).value))}
          />
        </label>

        <label className="modes-card__preview-toggle">
          <input
            type="checkbox"
            checked={showPreview}
            onChange={(event) => setShowPreview(event.target.checked)}
          />
          <span>Показать камеру (отладка распознавания руки)</span>
        </label>
        {showPreview && gestureActive && (
          <img className="modes-card__preview" src={gesturePreviewUrl()} alt="Превью камеры" />
        )}
      </div>

      <div className="modes-card">
        <div className="modes-card__head">
          <span className="modes-card__icon">
            <MessagesSquare size={20} />
          </span>
          <div className="modes-card__title-wrap">
            <span className="modes-card__title">Режим дискуссии</span>
            <span className="modes-card__status">Управляется голосом</span>
          </div>
          <button type="button" className="modes-card__toggle" onClick={() => void startDiscussion()}>
            Включить
          </button>
        </div>
        <p className="modes-card__hint">
          Ассистент молча слушает беседу и высказывает мнение по фразе «что думаешь, &lt;имя&gt;». Выход —
          «выйди из режима дискуссии». Обычные команды на время режима отключаются.
        </p>
      </div>

      {message && <p className="modes-panel__message">{message}</p>}

      {showInstructions && <GestureInstructions onClose={() => setShowInstructions(false)} />}
    </div>
  );
}
