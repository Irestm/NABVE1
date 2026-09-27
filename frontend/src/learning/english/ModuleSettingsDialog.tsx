import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getLevelFilter, getModuleSettings, reanalyzeLibrary, saveLevelFilter, saveModuleSettings } from "../../api/english";
import type { CefrLevel, LevelFilter, ModuleSettings } from "../../api/english";
import { Dialog } from "./Dialog";
import { LevelFilterEditor } from "./LevelFilterEditor";

interface ModuleSettingsDialogProps {
  onClose: () => void;
  onSaved: (settings: ModuleSettings, filter: LevelFilter) => void;
}

const USER_LEVELS: CefrLevel[] = ["A1", "A2", "B1", "B2", "C1", "C2"];

export function ModuleSettingsDialog({ onClose, onSaved }: ModuleSettingsDialogProps): JSX.Element {
  const [settings, setSettings] = useState<ModuleSettings | null>(null);
  const [filter, setFilter] = useState<LevelFilter | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([getModuleSettings(), getLevelFilter("global")])
      .then(([loadedSettings, loadedFilter]) => {
        setSettings(loadedSettings);
        setFilter({
          levels: loadedFilter.levels,
          include_unleveled: loadedFilter.include_unleveled,
          mwe_mode: loadedFilter.mwe_mode,
        });
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось загрузить настройки."));
  }, []);

  async function save(): Promise<void> {
    if (!settings || !filter) {
      return;
    }
    setBusy(true);
    try {
      const [savedSettings, savedFilter] = await Promise.all([
        saveModuleSettings(settings),
        saveLevelFilter("global", filter),
      ]);
      onSaved(savedSettings, savedFilter);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить.");
    } finally {
      setBusy(false);
    }
  }

  async function reanalyze(): Promise<void> {
    setBusy(true);
    setNotice("");
    try {
      const result = await reanalyzeLibrary();
      const failed = result.failed?.length ? ` Не удалось: ${result.failed.join("; ")}.` : "";
      setNotice(
        `Готово: ${result.candidates} кандидатов, в архив ушло ${result.archived} карточек, вернулось ${result.restored}.${failed}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось переанализировать.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title="Настройки английского" onClose={onClose}>
      {settings && filter ? (
        <>
          <label className="ql-field">
            <span className="ql-field__label">Мой уровень английского</span>
            <select
              className="ql-input ql-select"
              value={settings.user_level}
              onChange={(event) => setSettings({ ...settings, user_level: event.target.value as CefrLevel })}
            >
              {USER_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
          <LevelFilterEditor value={filter} onChange={setFilter} />
          <label className="ql-toggle-row">
            <span>
              <span className="ql-toggle-row__title">Разрешить подсказки с ответом</span>
              <span className="ql-muted ql-radio__hint">Ассистент сможет назвать перевод во время теста</span>
            </span>
            <input
              type="checkbox"
              className="ql-switch"
              checked={settings.allow_answer_hints}
              onChange={(event) => setSettings({ ...settings, allow_answer_hints: event.target.checked })}
            />
          </label>
          <div className="ql-row">
            <button type="button" className="ql-button ql-button--ghost" onClick={() => void reanalyze()} disabled={busy}>
              <RefreshCw size={16} /> Переанализировать импортированные серии
            </button>
          </div>
          {notice && <p className="ql-muted">{notice}</p>}
        </>
      ) : (
        <p className="ql-muted">Загрузка…</p>
      )}
      {error && <p className="ql-error">{error}</p>}
      <div className="ql-row ql-row--end">
        <button type="button" className="ql-button ql-button--ghost" onClick={onClose}>
          Отмена
        </button>
        <button type="button" className="ql-button ql-button--primary" onClick={() => void save()} disabled={busy || !settings}>
          Сохранить
        </button>
      </div>
    </Dialog>
  );
}
