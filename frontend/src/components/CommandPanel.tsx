import { Fragment, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  AlarmClockOff,
  Battery,
  BatteryCharging,
  CircleStop,
  DownloadCloud,
  FolderInput,
  FolderPlus,
  Gamepad2,
  Languages,
  Lock,
  MessagesSquare,
  Minimize2,
  Moon,
  PackagePlus,
  Power,
  RefreshCw,
  Timer,
  Trash2,
  Volume2,
  VolumeX,
  Watch,
  X,
} from "lucide-react";
import { confirmCommand, listCommandButtons, runCommand } from "../api/client";
import type { CommandButtonDescriptor, CommandParamField } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import { DiscussionEndButton } from "./DiscussionEndButton";
import { GestureModeControl } from "./GestureModeControl";
import "./CommandPanel.css";

// Matches the "icon" strings in core/command_ui_metadata.py exactly — one
// entry per command currently exposed on the panel.
const ICONS: Record<string, (props: { size?: number }) => ReactNode> = {
  Power,
  RefreshCw,
  Volume2,
  VolumeX,
  Minimize2,
  X,
  FolderPlus,
  FolderInput,
  Trash2,
  Languages,
  Battery,
  BatteryCharging,
  DownloadCloud,
  Gamepad2,
  Lock,
  MessagesSquare,
  Moon,
  PackagePlus,
  Timer,
  AlarmClockOff,
  Watch,
  CircleStop,
};

// Mirrors core/command_ui_metadata.py's GROUP_LABELS/GROUP_ORDER exactly —
// grouping replaced the old per-button golden-angle rainbow (explicit
// follow-up request: group the panel, one accent color per group instead
// of per button).
const GROUP_LABELS: Record<string, string> = {
  power: "Питание и система",
  sound: "Звук",
  windows: "Окна и вкладки",
  files: "Файлы",
  time_lang: "Время и язык",
  modes: "Режимы",
};
const GROUP_ORDER = ["power", "sound", "windows", "files", "time_lang", "modes"];
const GROUP_ACCENT: Record<string, string> = {
  power: "var(--accent-red)",
  sound: "var(--accent-blue)",
  windows: "var(--glow-listening)",
  files: "var(--accent-amber)",
  time_lang: "var(--accent-purple)",
  modes: "var(--accent-green)",
};
const DEFAULT_GROUP_ACCENT = "var(--accent-blue)";

function groupButtons(buttons: CommandButtonDescriptor[]): Array<[string, CommandButtonDescriptor[]]> {
  const byGroup = new Map<string, CommandButtonDescriptor[]>();
  for (const button of buttons) {
    const list = byGroup.get(button.group) ?? [];
    list.push(button);
    byGroup.set(button.group, list);
  }
  const ordered: Array<[string, CommandButtonDescriptor[]]> = [];
  for (const group of GROUP_ORDER) {
    const list = byGroup.get(group);
    if (list && list.length > 0) {
      ordered.push([group, list]);
      byGroup.delete(group);
    }
  }
  // Any group the backend adds later that this file hasn't been taught a
  // label/color for yet still shows up, just at the end, generically —
  // never silently drops buttons.
  for (const [group, list] of byGroup) {
    ordered.push([group, list]);
  }
  return ordered;
}

type FormValues = Record<string, string>;

function defaultFormValues(schema: CommandParamField[]): FormValues {
  const values: FormValues = {};
  for (const field of schema) {
    if (field.type === "select" && field.options && field.options.length > 0) {
      values[field.name] = field.options[0];
    } else if (field.type === "number") {
      values[field.name] = String(field.min ?? 0);
    } else {
      values[field.name] = "";
    }
  }
  return values;
}

function isFormComplete(schema: CommandParamField[], values: FormValues): boolean {
  return schema.every((field) => field.optional || (values[field.name] ?? "").trim() !== "");
}

function toParams(schema: CommandParamField[], values: FormValues): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const field of schema) {
    const raw = values[field.name] ?? "";
    if (field.optional && raw.trim() === "") {
      // Omitted entirely, not sent as 0/"" — e.g. toggle_timer reads a
      // missing "minutes" as "cancel every active timer", not "start one
      // for zero minutes".
      continue;
    }
    params[field.name] = field.type === "number" ? Number(raw) : raw;
  }
  return params;
}

// toggle_timer's UI is digital H/M/S entry (see TimerFields), not the
// schema-driven range slider every other bounded number field uses. The
// handler still receives a single "minutes" (float — seconds survive as a
// fraction); nothing entered omits it entirely, which the handler reads
// as "cancel every active timer" (see modules.timer.handlers).
function timerParamsFromHMS(values: FormValues): Record<string, unknown> {
  const hours = Math.max(0, Math.floor(Number(values.h) || 0));
  const minutes = Math.max(0, Math.floor(Number(values.m) || 0));
  const seconds = Math.max(0, Math.floor(Number(values.s) || 0));
  const totalSeconds = hours * 3600 + minutes * 60 + seconds;
  if (totalSeconds <= 0) {
    return {};
  }
  return { minutes: totalSeconds / 60 };
}

const TIMER_PRESETS_MIN = [1, 3, 5, 10, 15] as const;

function TimerFields({
  values,
  onChange,
}: {
  values: FormValues;
  onChange: (name: string, value: string) => void;
}): JSX.Element {
  const parts = [
    { name: "h", label: "ч", max: 23 },
    { name: "m", label: "мин", max: 59 },
    { name: "s", label: "сек", max: 59 },
  ] as const;
  return (
    <div className="command-panel__timer">
      <div className="command-panel__timer-fields">
        {parts.map((part, index) => (
          <Fragment key={part.name}>
            {index > 0 && <span className="command-panel__timer-colon">:</span>}
            <label className="command-panel__timer-part">
              <span className="command-panel__timer-unit">{part.label}</span>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                max={part.max}
                value={values[part.name] ?? "0"}
                onChange={(event) => onChange(part.name, event.target.value)}
              />
            </label>
          </Fragment>
        ))}
      </div>
      <div className="command-panel__timer-presets">
        {TIMER_PRESETS_MIN.map((minutes) => (
          <button
            key={minutes}
            type="button"
            onClick={() => {
              onChange("h", "0");
              onChange("m", String(minutes));
              onChange("s", "0");
            }}
          >
            {minutes} мин
          </button>
        ))}
      </div>
    </div>
  );
}

function formatStopwatch(totalMs: number): string {
  const clamped = Math.max(0, totalMs);
  const centis = Math.floor(clamped / 10) % 100;
  const totalSeconds = Math.floor(clamped / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  const cc = String(centis).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}.${cc}` : `${mm}:${ss}.${cc}`;
}

// Replaces the blind toggle_stopwatch button (one press = "started", next
// press = a message that scrolled off-screen) with a real ticking
// stopwatch. Purely client-side — the voice "запусти секундомер" path is
// untouched and independent. Collapsed it looks like any other command
// button; the first press expands it and starts the count.
function StopwatchControl({ accent }: { accent: string }): JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const [running, setRunning] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [accumulatedMs, setAccumulatedMs] = useState(0);
  const [nowMs, setNowMs] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!running || startedAt == null) {
      return;
    }
    const id = window.setInterval(() => setNowMs(Date.now()), 71);
    return () => window.clearInterval(id);
  }, [running, startedAt]);

  // Collapse back to a plain button when the click lands anywhere outside
  // the widget (the stopwatch and its own buttons keep it open). The
  // running count, if any, keeps ticking in state and reappears on the
  // next expand.
  useEffect(() => {
    if (!expanded) {
      return;
    }
    function onPointerDown(event: PointerEvent): void {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [expanded]);

  const shownMs = running && startedAt != null ? accumulatedMs + (nowMs - startedAt) : accumulatedMs;

  function start(): void {
    const t = Date.now();
    setStartedAt(t);
    setNowMs(t);
    setRunning(true);
  }

  function stop(): void {
    setAccumulatedMs((prev) => (startedAt != null ? prev + (Date.now() - startedAt) : prev));
    setStartedAt(null);
    setRunning(false);
  }

  function reset(): void {
    setAccumulatedMs(0);
    setStartedAt(null);
    setNowMs(0);
    setRunning(false);
  }

  if (!expanded) {
    return (
      <button
        type="button"
        className="command-panel__button"
        style={{ "--item-accent": accent } as CSSProperties}
        onClick={() => setExpanded(true)}
        title="Секундомер"
      >
        <Watch size={22} />
        <span>Секундомер</span>
      </button>
    );
  }

  return (
    <div
      ref={boxRef}
      className="command-panel__stopwatch"
      style={{ "--item-accent": accent } as CSSProperties}
    >
      <span className="command-panel__stopwatch-label">
        <Watch size={16} /> Секундомер
      </span>
      <span className="command-panel__stopwatch-display">{formatStopwatch(shownMs)}</span>
      <span className="command-panel__stopwatch-actions">
        {running ? (
          <button type="button" onClick={stop}>
            Стоп
          </button>
        ) : (
          <button type="button" onClick={start}>
            Старт
          </button>
        )}
        <button type="button" onClick={reset} disabled={running || shownMs === 0}>
          Сброс
        </button>
      </span>
    </div>
  );
}

function ParamFields({
  schema,
  values,
  onChange,
}: {
  schema: CommandParamField[];
  values: FormValues;
  onChange: (name: string, value: string) => void;
}): JSX.Element {
  return (
    <div className="command-panel__form-fields">
      {schema.map((field) => (
        <label key={field.name} className="command-panel__form-field">
          <span>{field.label}</span>
          {field.type === "select" && field.options ? (
            <select value={values[field.name] ?? ""} onChange={(event) => onChange(field.name, event.target.value)}>
              {field.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : field.type === "number" && field.min != null && field.max != null ? (
            <span className="command-panel__slider-row">
              <input
                type="range"
                min={field.min}
                max={field.max}
                value={values[field.name] ?? field.min}
                onChange={(event) => onChange(field.name, event.target.value)}
                style={
                  {
                    "--range-fill": `${
                      (((Number(values[field.name] ?? field.min) - field.min) / (field.max - field.min)) * 100).toFixed(2)
                    }%`,
                  } as CSSProperties
                }
              />
              <span className="command-panel__slider-value">{values[field.name]}</span>
            </span>
          ) : (
            <input
              type={field.type === "number" ? "number" : "text"}
              value={values[field.name] ?? ""}
              onChange={(event) => onChange(field.name, event.target.value)}
            />
          )}
        </label>
      ))}
    </div>
  );
}

// Commands that actually start something the user then wants to look at
// (a running board game, on the Ассистент tab's Игры panel) rather than
// just reading a confirmation message.
const NAVIGATE_TO_GAMES_ON: ReadonlySet<string> = new Set(["start_board_game"]);

interface CommandPanelProps {
  onNavigateToGames?: () => void;
}

export function CommandPanel({ onNavigateToGames }: CommandPanelProps): JSX.Element {
  const [buttons, setButtons] = useState<CommandButtonDescriptor[]>([]);
  const [loadError, setLoadError] = useState("");
  const [resultMessage, setResultMessage] = useState("");
  const [resultError, setResultError] = useState("");
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const [openCommand, setOpenCommand] = useState<CommandButtonDescriptor | null>(null);
  const [formValues, setFormValues] = useState<FormValues>({});

  useEffect(() => {
    let cancelled = false;
    listCommandButtons()
      .then((list) => {
        if (!cancelled) {
          setButtons(list);
        }
      })
      .catch((error) => {
        console.error("Failed to load command buttons:", error);
        if (!cancelled) {
          setLoadError("Не удалось загрузить список команд.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function execute(command: CommandButtonDescriptor, params: Record<string, unknown>): Promise<void> {
    setBusyCommand(command.name);
    setResultError("");
    try {
      let response = await runCommand(command.name, params);
      // Dangerous commands always come back confirmation_required first
      // (core/dispatcher.py's dispatch()) regardless of who called them —
      // the modal above is an independent UI-level check, this is the
      // separate backend-level one; both run, neither is skipped.
      if (response.status === "confirmation_required" && response.token) {
        response = await confirmCommand(response.token, true);
      }
      if (response.status === "failed") {
        setResultError(response.message || `Не удалось выполнить «${command.label}».`);
      } else {
        setResultMessage(response.message || `Команда «${command.label}» выполнена.`);
        if (NAVIGATE_TO_GAMES_ON.has(command.name) && onNavigateToGames) {
          // Also bumps gamesOpenSignal (see App.tsx) so the Board Games
          // card actually opens — scrolling to it while it's still
          // collapsed just shows the closed card, not the board.
          onNavigateToGames();
          // Two things need time before the board's final on-screen
          // position is stable enough to scroll to: the tab switch itself
          // re-mounting the Ассистент page's content (one frame), and the
          // card's own open transition (--transition-med, 320ms) actually
          // finishing — scrolling mid-expand targets a position that's
          // still moving. ".board-games-panel__board" (not the outer
          // panel) so the board itself ends up on screen, not just the
          // pre-game difficulty picker above it.
          setTimeout(() => {
            document
              .querySelector(".board-games-panel__board")
              ?.scrollIntoView({ behavior: "smooth", block: "center" });
          }, 360);
        }
      }
    } catch (error) {
      console.error(`Command ${command.name} failed:`, error);
      setResultError(`Не удалось выполнить «${command.label}».`);
    } finally {
      setBusyCommand(null);
      setOpenCommand(null);
    }
  }

  function handleClick(command: CommandButtonDescriptor): void {
    setResultMessage("");
    setResultError("");
    if ((command.params_schema && command.params_schema.length > 0) || command.dangerous) {
      if (command.name === "toggle_timer") {
        setFormValues({ h: "0", m: "5", s: "0" });
      } else {
        setFormValues(command.params_schema ? defaultFormValues(command.params_schema) : {});
      }
      setOpenCommand(command);
      return;
    }
    void execute(command, {});
  }

  const schema = openCommand?.params_schema ?? null;
  const formReady = !schema || isFormComplete(schema, formValues);
  const groups = groupButtons(buttons);

  return (
    <div className="section command-panel">
      <h3>Команды</h3>
      {loadError && <p className="status-error">{loadError}</p>}

      {(resultMessage || resultError) && (
        <p
          className={
            resultError
              ? "status-error command-panel__result command-panel__result--top"
              : "command-panel__result command-panel__result--top"
          }
          role="status"
        >
          {resultError || resultMessage}
        </p>
      )}

      {groups.map(([group, groupCommands]) => (
        <div key={group} className="command-panel__group">
          <span
            className="command-panel__group-label"
            style={{ "--item-accent": GROUP_ACCENT[group] ?? DEFAULT_GROUP_ACCENT } as CSSProperties}
          >
            {GROUP_LABELS[group] ?? group}
          </span>
          <div className="command-panel__grid">
            {group === "modes" && (
              <>
                <GestureModeControl accent={GROUP_ACCENT[group] ?? DEFAULT_GROUP_ACCENT} />
                <DiscussionEndButton accent={GROUP_ACCENT[group] ?? DEFAULT_GROUP_ACCENT} />
              </>
            )}
            {group === "time_lang" && (
              <StopwatchControl accent={GROUP_ACCENT[group] ?? DEFAULT_GROUP_ACCENT} />
            )}
            {groupCommands.map((command) => {
              // Rendered above as a live ticking widget, not a blind toggle button.
              if (command.name === "toggle_stopwatch") {
                return null;
              }
              const Icon = ICONS[command.icon];
              return (
                <button
                  key={command.name}
                  type="button"
                  className="command-panel__button"
                  style={{ "--item-accent": GROUP_ACCENT[group] ?? DEFAULT_GROUP_ACCENT } as CSSProperties}
                  disabled={busyCommand === command.name}
                  onClick={() => handleClick(command)}
                  title={command.description}
                >
                  {Icon && <Icon size={22} />}
                  <span>{command.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {openCommand && (
        <ConfirmDialog
          title={openCommand.dangerous ? `Вы уверены? — ${openCommand.label}` : openCommand.label}
          message={
            openCommand.dangerous
              ? "Это действие необратимо. Подтвердите, что хотите его выполнить."
              : openCommand.name === "toggle_timer"
                ? "Введите время. Пусто (0:00:00) — отменить все активные таймеры."
                : "Заполните параметры и подтвердите выполнение."
          }
          tone={openCommand.dangerous ? "danger" : "neutral"}
          confirmLabel={openCommand.dangerous ? "Да, выполнить" : "Выполнить"}
          busy={busyCommand === openCommand.name}
          confirmDisabled={!formReady}
          onCancel={() => setOpenCommand(null)}
          onConfirm={() => {
            if (!formReady) {
              return;
            }
            const params =
              openCommand.name === "toggle_timer"
                ? timerParamsFromHMS(formValues)
                : schema
                  ? toParams(schema, formValues)
                  : {};
            void execute(openCommand, params);
          }}
        >
          {openCommand.name === "toggle_timer" ? (
            <TimerFields
              values={formValues}
              onChange={(name, value) => setFormValues((prev) => ({ ...prev, [name]: value }))}
            />
          ) : (
            schema && (
              <ParamFields
                schema={schema}
                values={formValues}
                onChange={(name, value) => setFormValues((prev) => ({ ...prev, [name]: value }))}
              />
            )
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
