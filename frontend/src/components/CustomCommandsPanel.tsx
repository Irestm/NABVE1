import { useEffect, useState } from "react";
import {
  AppWindow,
  Image as ImageIcon,
  Link2,
  type LucideIcon,
  MessageSquareText,
  Music,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { deleteCustomCommand, getProfileFact, listCustomCommands, saveCustomCommand, setProfileFact } from "../api/client";
import { isElectron } from "../platform/electronAdapter";
import type { CustomCommand, CustomCommandActionType } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import "./CustomCommandsPanel.css";

// Matches modules/user_profile/domain.py's STOP_WORD_KEY/WAKE_PHRASE_KEY/
// CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY and modules/tray_hide/config.py's
// HIDE_PHRASE_KEY/SHOW_PHRASE_KEY exactly — these fields used to live in
// components/PersonalityPanel.tsx; moved here as the "Системные команды"
// section, single source of truth now that this tab exists.
const STOP_WORD_KEY = "stop_word";
const WAKE_PHRASE_KEY = "wake_phrase";
const TRAY_HIDE_PHRASE_KEY = "tray_hide_phrase";
const TRAY_SHOW_PHRASE_KEY = "tray_show_phrase";
const CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY = "custom_commands_require_confirmation";

const ACTION_TYPE_LABELS: Record<CustomCommandActionType, string> = {
  open_link: "Открыть ссылку",
  play_audio: "Воспроизвести аудио",
  open_media: "Открыть фото/видео",
  launch_app: "Запустить приложение",
  text_instruction: "Текстовая инструкция",
};

const ACTION_TYPE_ICONS: Record<CustomCommandActionType, LucideIcon> = {
  open_link: Link2,
  play_audio: Music,
  open_media: ImageIcon,
  launch_app: AppWindow,
  text_instruction: MessageSquareText,
};

function fileNameFromPath(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function payloadPreview(command: CustomCommand): string {
  switch (command.action_type) {
    case "open_link":
      return command.action_payload.url ?? "";
    case "play_audio":
    case "open_media":
      return command.action_payload.file_path ? fileNameFromPath(command.action_payload.file_path) : "";
    case "launch_app":
      return command.action_payload.executable_path ?? "";
    case "text_instruction":
      return command.action_payload.instruction ?? "";
    default:
      return "";
  }
}

interface FormState {
  triggerPhrase: string;
  actionType: CustomCommandActionType;
  url: string;
  executablePath: string;
  instruction: string;
  mediaType: "photo" | "video";
  file: File | null;
}

const EMPTY_FORM: FormState = {
  triggerPhrase: "",
  actionType: "open_link",
  url: "",
  executablePath: "",
  instruction: "",
  mediaType: "photo",
  file: null,
};

export function CustomCommandsPanel(): JSX.Element {
  // --- Системные команды ---------------------------------------------------
  const [stopWord, setStopWord] = useState("");
  const [stopWordInput, setStopWordInput] = useState("");
  const [wakePhrase, setWakePhrase] = useState("");
  const [wakePhraseInput, setWakePhraseInput] = useState("");
  const [trayHidePhrase, setTrayHidePhrase] = useState("");
  const [trayHidePhraseInput, setTrayHidePhraseInput] = useState("");
  const [trayShowPhrase, setTrayShowPhrase] = useState("");
  const [trayShowPhraseInput, setTrayShowPhraseInput] = useState("");
  const [requireConfirmation, setRequireConfirmation] = useState(false);
  const [savingRequireConfirmation, setSavingRequireConfirmation] = useState(false);

  // --- Мои команды -----------------------------------------------------------
  const [commands, setCommands] = useState<CustomCommand[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<CustomCommand | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [word, wake, hide, show, requireConfirm, list] = await Promise.all([
          getProfileFact(STOP_WORD_KEY),
          getProfileFact(WAKE_PHRASE_KEY),
          getProfileFact(TRAY_HIDE_PHRASE_KEY),
          getProfileFact(TRAY_SHOW_PHRASE_KEY),
          getProfileFact(CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY),
          listCustomCommands(),
        ]);
        if (cancelled) {
          return;
        }
        setStopWord(word ?? "");
        setStopWordInput(word ?? "");
        setWakePhrase(wake ?? "");
        setWakePhraseInput(wake ?? "");
        setTrayHidePhrase(hide ?? "");
        setTrayHidePhraseInput(hide ?? "");
        setTrayShowPhrase(show ?? "");
        setTrayShowPhraseInput(show ?? "");
        setRequireConfirmation(requireConfirm === "1");
        setCommands(list);
        setLoaded(true);
      } catch (err) {
        if (cancelled) {
          return;
        }
        console.error("Failed to load custom commands settings:", err);
        setError("Не удалось загрузить настройки команд.");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSaveStopWord(): Promise<void> {
    const trimmed = stopWordInput.trim();
    if (!trimmed) {
      return;
    }
    try {
      await setProfileFact(STOP_WORD_KEY, trimmed);
      setStopWord(trimmed);
    } catch (err) {
      console.error("Failed to save the stop word:", err);
      setError("Не удалось сохранить стоп-слово.");
    }
  }

  async function handleSaveWakePhrase(): Promise<void> {
    const trimmed = wakePhraseInput.trim();
    if (!trimmed) {
      return;
    }
    try {
      await setProfileFact(WAKE_PHRASE_KEY, trimmed);
      setWakePhrase(trimmed);
    } catch (err) {
      console.error("Failed to save the wake phrase:", err);
      setError("Не удалось сохранить активационную фразу.");
    }
  }

  async function handleSaveTrayHidePhrase(): Promise<void> {
    const trimmed = trayHidePhraseInput.trim();
    if (!trimmed) {
      return;
    }
    try {
      await setProfileFact(TRAY_HIDE_PHRASE_KEY, trimmed);
      setTrayHidePhrase(trimmed);
    } catch (err) {
      console.error("Failed to save the tray-hide phrase:", err);
      setError("Не удалось сохранить фразу скрытия.");
    }
  }

  async function handleSaveTrayShowPhrase(): Promise<void> {
    const trimmed = trayShowPhraseInput.trim();
    if (!trimmed) {
      return;
    }
    try {
      await setProfileFact(TRAY_SHOW_PHRASE_KEY, trimmed);
      setTrayShowPhrase(trimmed);
    } catch (err) {
      console.error("Failed to save the tray-show phrase:", err);
      setError("Не удалось сохранить фразу возврата.");
    }
  }

  async function handleToggleRequireConfirmation(): Promise<void> {
    const next = !requireConfirmation;
    setSavingRequireConfirmation(true);
    try {
      await setProfileFact(CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY, next ? "1" : "0");
      setRequireConfirmation(next);
    } catch (err) {
      console.error("Failed to save the confirmation setting:", err);
      setError("Не удалось сохранить настройку подтверждения.");
    } finally {
      setSavingRequireConfirmation(false);
    }
  }

  async function refreshCommands(): Promise<void> {
    try {
      setCommands(await listCustomCommands());
    } catch (err) {
      console.error("Failed to reload custom commands:", err);
    }
  }

  function openCreateForm(): void {
    setForm(EMPTY_FORM);
    setEditing(null);
    setFormOpen(true);
  }

  function openEditForm(command: CustomCommand): void {
    setForm({
      triggerPhrase: command.trigger_phrase,
      actionType: command.action_type,
      url: command.action_payload.url ?? "",
      executablePath: command.action_payload.executable_path ?? "",
      instruction: command.action_payload.instruction ?? "",
      mediaType: command.action_payload.media_type === "video" ? "video" : "photo",
      file: null,
    });
    setEditing(command);
    setFormOpen(true);
  }

  function closeForm(): void {
    setFormOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  const formReady =
    form.triggerPhrase.trim() !== "" &&
    (form.actionType === "open_link"
      ? form.url.trim() !== ""
      : form.actionType === "launch_app"
        ? form.executablePath.trim() !== ""
        : form.actionType === "text_instruction"
          ? form.instruction.trim() !== ""
          : // play_audio / open_media: a new file is required when creating;
            // editing without picking a new one keeps the existing attachment
            // (see core/main.py's create_or_update_custom_command).
            form.file !== null || editing !== null);

  async function handleSubmit(): Promise<void> {
    if (!formReady) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await saveCustomCommand({
        commandId: editing?.id,
        triggerPhrase: form.triggerPhrase.trim(),
        actionType: form.actionType,
        url: form.actionType === "open_link" ? form.url.trim() : undefined,
        executablePath: form.actionType === "launch_app" ? form.executablePath.trim() : undefined,
        instruction: form.actionType === "text_instruction" ? form.instruction.trim() : undefined,
        mediaType: form.actionType === "open_media" ? form.mediaType : undefined,
        file: form.file,
      });
      closeForm();
      await refreshCommands();
    } catch (err) {
      console.error("Failed to save custom command:", err);
      setError("Не удалось сохранить команду.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(command: CustomCommand): Promise<void> {
    setDeletingId(command.id);
    setError("");
    try {
      await deleteCustomCommand(command.id);
      await refreshCommands();
    } catch (err) {
      console.error("Failed to delete custom command:", err);
      setError("Не удалось удалить команду.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handlePickExecutable(): Promise<void> {
    try {
      const path = await window.assistantAPI?.pickExecutablePath?.();
      if (path) {
        setForm((prev) => ({ ...prev, executablePath: path }));
      }
    } catch (err) {
      console.error("Failed to pick an executable path:", err);
      setError("Не удалось открыть диалог выбора файла.");
    }
  }

  return (
    <div className="section custom-commands-panel">
      <h3>Мои команды</h3>
      {error && <p className="status-error">{error}</p>}
      {!loaded && !error && <p className="status-detail">Загрузка…</p>}

      <div className="custom-commands-panel__group">
        <span className="custom-commands-panel__subheading">Системные команды</span>

        <div className="personality-panel__field">
          <span className="personality-panel__label">Стоп-слово</span>
          <div className="row">
            <input
              type="text"
              value={stopWordInput}
              onChange={(event) => setStopWordInput(event.target.value)}
              placeholder="Слово для паузы и возобновления"
            />
            <button
              onClick={() => void handleSaveStopWord()}
              disabled={!stopWordInput.trim() || stopWordInput.trim() === stopWord}
            >
              Сохранить
            </button>
          </div>
        </div>

        <div className="personality-panel__field">
          <span className="personality-panel__label">Активационная фраза</span>
          <div className="row">
            <input
              type="text"
              value={wakePhraseInput}
              onChange={(event) => setWakePhraseInput(event.target.value)}
              placeholder='Добавляется к фразам по умолчанию ("привет", "эй джарвис")'
            />
            <button
              onClick={() => void handleSaveWakePhrase()}
              disabled={!wakePhraseInput.trim() || wakePhraseInput.trim() === wakePhrase}
            >
              Сохранить
            </button>
          </div>
        </div>

        <div className="personality-panel__field">
          <span className="personality-panel__label">Скрытие в трей</span>
          <div className="row">
            <input
              type="text"
              value={trayHidePhraseInput}
              onChange={(event) => setTrayHidePhraseInput(event.target.value)}
              placeholder='Фраза скрытия (по умолчанию "спрячься")'
            />
            <button
              onClick={() => void handleSaveTrayHidePhrase()}
              disabled={!trayHidePhraseInput.trim() || trayHidePhraseInput.trim() === trayHidePhrase}
            >
              Сохранить
            </button>
          </div>
          <div className="row">
            <input
              type="text"
              value={trayShowPhraseInput}
              onChange={(event) => setTrayShowPhraseInput(event.target.value)}
              placeholder='Фраза возврата (по умолчанию "покажись")'
            />
            <button
              onClick={() => void handleSaveTrayShowPhrase()}
              disabled={!trayShowPhraseInput.trim() || trayShowPhraseInput.trim() === trayShowPhrase}
            >
              Сохранить
            </button>
          </div>
        </div>

        <label className="personality-panel__checkbox">
          <input
            type="checkbox"
            checked={requireConfirmation}
            disabled={savingRequireConfirmation}
            onChange={() => void handleToggleRequireConfirmation()}
          />
          Требовать подтверждение перед выполнением непроверенных кастомных команд
        </label>
      </div>

      <div className="custom-commands-panel__group">
        <div className="custom-commands-panel__list-header">
          <span className="custom-commands-panel__subheading">Мои команды</span>
          <button
            type="button"
            className="custom-commands-panel__add"
            onClick={openCreateForm}
            title="Добавить команду"
          >
            <Plus size={18} />
          </button>
        </div>

        {loaded && commands.length === 0 && <p className="status-detail">Команд пока нет.</p>}

        <div className="custom-commands-panel__cards">
          {commands.map((command) => {
            const Icon = ACTION_TYPE_ICONS[command.action_type];
            const preview = payloadPreview(command);
            return (
              <div key={command.id} className="custom-commands-panel__card">
                <Icon size={20} />
                <div className="custom-commands-panel__card-body">
                  <span className="custom-commands-panel__card-phrase">{command.trigger_phrase}</span>
                  <span className="custom-commands-panel__card-meta">
                    {ACTION_TYPE_LABELS[command.action_type]}
                    {preview && ` — ${preview}`}
                  </span>
                </div>
                <div className="custom-commands-panel__card-actions">
                  <button type="button" onClick={() => openEditForm(command)} title="Редактировать">
                    <Pencil size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(command)}
                    disabled={deletingId === command.id}
                    title="Удалить"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {formOpen && (
        <ConfirmDialog
          title={editing ? "Редактировать команду" : "Новая команда"}
          message="Задайте фразу активации и действие."
          tone="neutral"
          confirmLabel={editing ? "Сохранить" : "Создать команду"}
          busy={saving}
          confirmDisabled={!formReady}
          onCancel={closeForm}
          onConfirm={() => void handleSubmit()}
        >
          <div className="command-panel__form-fields">
            <label className="command-panel__form-field">
              <span>Фраза активации</span>
              <input
                type="text"
                value={form.triggerPhrase}
                onChange={(event) => setForm((prev) => ({ ...prev, triggerPhrase: event.target.value }))}
              />
            </label>

            <label className="command-panel__form-field">
              <span>Тип действия</span>
              <select
                value={form.actionType}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    actionType: event.target.value as CustomCommandActionType,
                    file: null,
                  }))
                }
                disabled={editing !== null}
              >
                {(Object.entries(ACTION_TYPE_LABELS) as [CustomCommandActionType, string][]).map(
                  ([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ),
                )}
              </select>
            </label>

            {form.actionType === "open_link" && (
              <label className="command-panel__form-field">
                <span>Ссылка</span>
                <input
                  type="text"
                  value={form.url}
                  onChange={(event) => setForm((prev) => ({ ...prev, url: event.target.value }))}
                  placeholder="https://..."
                />
              </label>
            )}

            {(form.actionType === "play_audio" || form.actionType === "open_media") && (
              <>
                {form.actionType === "open_media" && (
                  <label className="command-panel__form-field">
                    <span>Тип медиа</span>
                    <select
                      value={form.mediaType}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, mediaType: event.target.value as "photo" | "video" }))
                      }
                    >
                      <option value="photo">Фото</option>
                      <option value="video">Видео</option>
                    </select>
                  </label>
                )}
                <label className="command-panel__form-field">
                  <span>{form.actionType === "play_audio" ? "Аудиофайл" : "Файл"}</span>
                  <input
                    type="file"
                    accept={form.actionType === "play_audio" ? "audio/*" : "image/*,video/*"}
                    onChange={(event) => setForm((prev) => ({ ...prev, file: event.target.files?.[0] ?? null }))}
                  />
                  {editing && !form.file && (
                    <span className="status-detail">Оставьте пустым, чтобы сохранить текущий файл.</span>
                  )}
                </label>
              </>
            )}

            {form.actionType === "launch_app" && (
              <label className="command-panel__form-field">
                <span>Путь к исполняемому файлу</span>
                <div className="row">
                  <input
                    type="text"
                    value={form.executablePath}
                    onChange={(event) => setForm((prev) => ({ ...prev, executablePath: event.target.value }))}
                    placeholder="/usr/bin/..."
                  />
                  {isElectron() && (
                    <button type="button" onClick={() => void handlePickExecutable()}>
                      Обзор…
                    </button>
                  )}
                </div>
              </label>
            )}

            {form.actionType === "text_instruction" && (
              <label className="command-panel__form-field">
                <span>Инструкция</span>
                <textarea
                  rows={3}
                  value={form.instruction}
                  onChange={(event) => setForm((prev) => ({ ...prev, instruction: event.target.value }))}
                />
              </label>
            )}
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}
