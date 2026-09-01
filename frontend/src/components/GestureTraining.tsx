import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Check, RefreshCw, X } from "lucide-react";
import type { GestureCalibration } from "../types";
import "./GestureTraining.css";

// Full-screen "Обучение" game.
//   intro   — режим уже включён, просим раскрыть ладонь и лопнуть стартовый
//             шар кулаком (подтверждаем, что руку видно и клик работает).
//   steady / corners / click — ведёт бэкенд-сессия калибровки (phase_key);
//             лопанье шариков = визуальный отклик, прогресс = reps.
//   rightclick / scroll — фронт ведёт сам, без замеров (тренировка).
//   finished — 🎉 и авто-закрытие.

interface GestureTrainingProps {
  calibration: GestureCalibration | null;
  onExit: () => void;
  onCancelBackend: () => void;
  onFinished: () => void; // whole flow done (incl. practice) — game speaks here
}

type Step = "intro" | "steady" | "corners" | "click" | "rightclick" | "scroll" | "finished";

const BACKEND_STEPS: Step[] = ["steady", "corners", "click"];

const POSE: Record<Step, { glyph: string; pose: string }> = {
  intro: { glyph: "🖐️", pose: "Режим включён. Раскрой ладонь к камере — так система тебя увидит" },
  steady: { glyph: "☝️", pose: "Один указательный палец, ладонь к камере" },
  corners: { glyph: "☝️", pose: "Тот же указательный — тянемся им до краёв экрана" },
  click: { glyph: "✊", pose: "Наводишься указательным, потом сжимаешь всё в кулак" },
  rightclick: { glyph: "👍", pose: "Кулак + большой палец в сторону (жест «класс»)" },
  scroll: { glyph: "✌️", pose: "Указательный и средний вместе, ведёшь кистью вниз" },
  finished: { glyph: "✅", pose: "" },
};

// ball layouts per round — [x%, y%]. Later rounds spread wider / lower.
const LAYOUTS: Array<Array<[number, number]>> = [
  [
    [18, 24],
    [82, 30],
    [50, 78],
  ],
  [
    [12, 68],
    [88, 72],
    [50, 20],
  ],
  [
    [22, 84],
    [78, 82],
    [50, 48],
  ],
];

const CORNER_LAYOUT: Array<[number, number]> = [
  [5, 8],
  [95, 8],
  [5, 92],
  [95, 92],
];

const BALL_COLOURS = ["#ff4d4f", "#4d79ff", "#ffd24d"];
const BALL_NAMES = ["красный", "синий", "жёлтый"];

export function GestureTraining({
  calibration,
  onExit,
  onCancelBackend,
  onFinished,
}: GestureTrainingProps): JSX.Element {
  const [step, setStep] = useState<Step>("intro");
  const [started, setStarted] = useState(false);
  const [round, setRound] = useState(0);
  const [popped, setPopped] = useState<number[]>([]);
  const [scrollFrac, setScrollFrac] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const sawBackendRef = useRef(false);
  const finishedRef = useRef(false);

  // best-effort fullscreen while the game is open
  useEffect(() => {
    const el = rootRef.current;
    el?.requestFullscreen?.().catch(() => undefined);
    return () => {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    };
  }, []);

  // fresh ball state whenever the step changes
  useEffect(() => {
    setPopped([]);
  }, [step]);

  // once the user has started, follow the backend calibration phase
  useEffect(() => {
    if (!started || !calibration) return;
    const key = calibration.phase_key;
    if (key === "steady" || key === "corners" || key === "click") {
      sawBackendRef.current = true;
      setStep((s) => (s === key ? s : key));
    } else if (key === "done") {
      sawBackendRef.current = true;
    }
  }, [started, calibration?.phase_key]);

  // backend session cleared AFTER we actually saw it run => it finished on
  // its own; move on to the practice steps. Never fires before the user
  // started (so the mount-time null can't skip anything).
  useEffect(() => {
    if (
      started &&
      calibration === null &&
      sawBackendRef.current &&
      BACKEND_STEPS.includes(step)
    ) {
      setStep("rightclick");
    }
  }, [started, calibration, step]);

  const layout = useMemo(() => LAYOUTS[round % LAYOUTS.length], [round]);

  function pop(i: number): void {
    setPopped((p) => (p.includes(i) ? p : [...p, i]));
  }

  function refreshBalls(): void {
    setRound((r) => r + 1);
    setPopped([]);
  }

  function onScrollArea(e: React.UIEvent<HTMLDivElement>): void {
    const el = e.currentTarget;
    const max = el.scrollHeight - el.clientHeight;
    setScrollFrac(max > 0 ? el.scrollTop / max : 0);
  }

  // practice auto-advance
  useEffect(() => {
    if (step === "rightclick" && popped.length >= 3) {
      const t = window.setTimeout(() => setStep("scroll"), 900);
      return () => window.clearTimeout(t);
    }
    if (step === "scroll" && scrollFrac >= 0.98) {
      const t = window.setTimeout(() => setStep("finished"), 700);
      return () => window.clearTimeout(t);
    }
    if (step === "finished") {
      if (!finishedRef.current) {
        finishedRef.current = true;
        onFinished();
      }
      const t = window.setTimeout(onExit, 2400);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [step, popped.length, scrollFrac, onExit, onFinished]);

  const stepIndex =
    (["steady", "corners", "click", "rightclick", "scroll"] as Step[]).indexOf(step) + 1;
  const repsDone = calibration?.reps_done ?? 0;
  const repsTarget = calibration?.reps_target ?? 3;

  return (
    <div className="gtrain" ref={rootRef} role="dialog" aria-label="Обучение жестам">
      <div className="gtrain__top">
        <div className="gtrain__crumbs">
          {["Наведись", "Края", "Кулак", "Правый клик", "Скролл"].map((name, i) => (
            <span
              key={name}
              className={
                "gtrain__crumb" +
                (stepIndex > 0 && i + 1 < stepIndex ? " gtrain__crumb--done" : "") +
                (i + 1 === stepIndex ? " gtrain__crumb--now" : "")
              }
            >
              {stepIndex > 0 && i + 1 < stepIndex ? <Check size={12} strokeWidth={3} /> : i + 1}
              <em>{name}</em>
            </span>
          ))}
        </div>
        <button
          type="button"
          className="gtrain__quit"
          onClick={() => {
            onCancelBackend();
            onExit();
          }}
        >
          <X size={16} /> Прервать обучение
        </button>
      </div>

      {step !== "finished" ? (
        <div className="gtrain__pose">
          <span className="gtrain__glyph">{POSE[step].glyph}</span>
          <span className="gtrain__posetext">{POSE[step].pose}</span>
        </div>
      ) : null}

      {step === "intro" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Режим жестов включён. Раскрой ладонь к камере, потом наведись указательным на шар и
            сожми кулак — так мы убедимся, что руку видно, и начнём.
          </p>
          <div className="gtrain__center">
            <Ball colour="#5ad1a5" big onClick={() => setStarted(true)} />
          </div>
          {started ? <p className="gtrain__hint">Отлично! Ждём камеру…</p> : null}
        </div>
      ) : null}

      {step === "steady" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Наведись указательным на шар в центре и держи руку спокойно пару секунд.
          </p>
          <div className="gtrain__center">
            <Ball colour="#5ad1a5" filled={repsTarget > 0 ? repsDone / repsTarget : 0} big />
          </div>
          <Progress done={repsDone} target={repsTarget} />
        </div>
      ) : null}

      {step === "corners" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Разведи руку ШИРОКО: тянись указательным к каждому шару у самого края —
            вправо до предела, влево, вверх, вниз. Двигай всю руку, не только палец.
          </p>
          {CORNER_LAYOUT.map(([x, y], i) => {
            const lit = Math.round((repsDone / Math.max(repsTarget, 1)) * CORNER_LAYOUT.length);
            return (
              <div
                key={i}
                className="gtrain__ball-slot"
                style={{ left: `${x}%`, top: `${y}%` } as CSSProperties}
              >
                <Ball colour="#5ad1a5" filled={i < lit ? 1 : 0} />
              </div>
            );
          })}
          <Progress done={repsDone} target={repsTarget} />
        </div>
      ) : null}

      {step === "click" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Наведись на {BALL_NAMES[Math.min(repsDone, 2)]} шар и сожми кулак — он лопнет.
            Повтори с каждым.
          </p>
          {layout.map(([x, y], i) => (
            <div
              key={i}
              className="gtrain__ball-slot"
              style={{ left: `${x}%`, top: `${y}%` } as CSSProperties}
            >
              <Ball
                colour={BALL_COLOURS[i]}
                popped={i < repsDone || popped.includes(i)}
                onClick={() => pop(i)}
              />
            </div>
          ))}
          <div className="gtrain__actions">
            <button type="button" className="gtrain__refresh" onClick={refreshBalls}>
              <RefreshCw size={14} /> Обновить шарики
            </button>
          </div>
          <Progress done={repsDone} target={repsTarget} />
        </div>
      ) : null}

      {step === "rightclick" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Покажи «класс» (👍), наведясь на шар — правый клик его лопнет. Лопни все три.
          </p>
          {layout.map(([x, y], i) => (
            <div
              key={i}
              className="gtrain__ball-slot"
              style={{ left: `${x}%`, top: `${y}%` } as CSSProperties}
            >
              <Ball
                colour={BALL_COLOURS[i]}
                popped={popped.includes(i)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  pop(i);
                }}
                onClick={(e) => e.preventDefault()}
              />
            </div>
          ))}
          <div className="gtrain__actions">
            <button type="button" className="gtrain__refresh" onClick={refreshBalls}>
              <RefreshCw size={14} /> Обновить шарики
            </button>
          </div>
          <Progress done={popped.length} target={3} />
        </div>
      ) : null}

      {step === "scroll" ? (
        <div className="gtrain__stage">
          <p className="gtrain__task">
            Подними указательный и средний вместе, веди кистью вниз — долистай список до конца.
          </p>
          <div className="gtrain__scrollbox" onScroll={onScrollArea}>
            {Array.from({ length: 40 }).map((_, i) => (
              <div key={i} className="gtrain__scrollrow">
                Строка {i + 1}
              </div>
            ))}
            <div className="gtrain__scrollend">
              {scrollFrac >= 0.98 ? "Отлично, долистал!" : "…листай сюда…"}
            </div>
          </div>
          <div className="gtrain__scrollbar">
            <div className="gtrain__scrollbar-fill" style={{ width: `${Math.round(scrollFrac * 100)}%` }} />
          </div>
        </div>
      ) : null}

      {step === "finished" ? (
        <div className="gtrain__stage gtrain__stage--finish">
          <span className="gtrain__glyph gtrain__glyph--big">🎉</span>
          <p className="gtrain__task">Обучение пройдено. Управление подстроено под тебя.</p>
        </div>
      ) : null}
    </div>
  );
}

function Progress({ done, target }: { done: number; target: number }): JSX.Element {
  return (
    <div className="gtrain__dots">
      {Array.from({ length: Math.max(target, 1) }).map((_, i) => (
        <span key={i} className={"gtrain__dot" + (i < done ? " gtrain__dot--on" : "")} />
      ))}
    </div>
  );
}

interface BallProps {
  colour: string;
  popped?: boolean;
  filled?: number | boolean;
  big?: boolean;
  onClick?: (e: React.MouseEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}

function Ball({ colour, popped, filled, big, onClick, onContextMenu }: BallProps): JSX.Element {
  const f = typeof filled === "number" ? Math.max(0, Math.min(1, filled)) : filled ? 1 : 0;
  return (
    <button
      type="button"
      className={
        "gtrain__ball" +
        (popped ? " gtrain__ball--popped" : "") +
        (big ? " gtrain__ball--big" : "")
      }
      style={{ "--ball": colour, "--fill": String(f) } as CSSProperties}
      onClick={onClick}
      onContextMenu={onContextMenu}
      aria-label="шар"
    />
  );
}
