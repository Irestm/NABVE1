import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  AlarmClockOff,
  Battery,
  CircleStop,
  Crown,
  Disc,
  DownloadCloud,
  FolderInput,
  FolderPlus,
  Languages,
  type LucideIcon,
  Minimize2,
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
import "./CommandPanel.css";

// Matches the "icon" strings in core/command_ui_metadata.py exactly — one
// entry per command currently exposed on the panel.
const ICONS: Record<string, LucideIcon> = {
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
  DownloadCloud,
  Crown,
  Disc,
  Timer,
  AlarmClockOff,
  Watch,
  CircleStop,
};

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
const NAVIGATE_TO_GAMES_ON: ReadonlySet<string> = new Set(["start_chess_game", "start_checkers_game"]);

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
          onNavigateToGames();
          // The tab switch above re-renders the Ассистент tab's content
          // fresh — give it a frame to actually mount before scrolling to
          // an element that doesn't exist yet.
          requestAnimationFrame(() => {
            document.querySelector(".board-games-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
          });
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
      setFormValues(command.params_schema ? defaultFormValues(command.params_schema) : {});
      setOpenCommand(command);
      return;
    }
    void execute(command, {});
  }

  const schema = openCommand?.params_schema ?? null;
  const formReady = !schema || isFormComplete(schema, formValues);

  return (
    <div className="section command-panel">
      <h3>Команды</h3>
      {loadError && <p className="status-error">{loadError}</p>}

      <div className="command-panel__grid">
        {buttons.map((command) => {
          const Icon = ICONS[command.icon];
          return (
            <button
              key={command.name}
              type="button"
              className="command-panel__button"
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

      {(resultMessage || resultError) && (
        <p className={resultError ? "status-error" : "command-panel__result"}>{resultError || resultMessage}</p>
      )}

      {openCommand && (
        <ConfirmDialog
          title={openCommand.dangerous ? `Вы уверены? — ${openCommand.label}` : openCommand.label}
          message={
            openCommand.dangerous
              ? "Это действие необратимо. Подтвердите, что хотите его выполнить."
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
            void execute(openCommand, schema ? toParams(schema, formValues) : {});
          }}
        >
          {schema && (
            <ParamFields
              schema={schema}
              values={formValues}
              onChange={(name, value) => setFormValues((prev) => ({ ...prev, [name]: value }))}
            />
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
