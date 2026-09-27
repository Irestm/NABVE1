import { useEffect, useState } from "react";
import { getLevelFilter, resetLevelFilter, saveLevelFilter } from "../../api/english";
import type { FilterScope, LevelFilter, LevelFilterView } from "../../api/english";
import { Dialog } from "./Dialog";
import { LevelFilterEditor } from "./LevelFilterEditor";

interface FilterOverrideDialogProps {
  scope: Exclude<FilterScope, "global">;
  scopeId: number;
  label: string;
  onClose: () => void;
  onChanged: (view: LevelFilterView) => void;
}

const SOURCE_LABELS: Record<FilterScope, string> = {
  global: "сейчас действуют глобальные настройки модуля",
  title: "сейчас действуют настройки тайтла",
  episode: "сейчас действуют настройки этого эпизода",
};

export function FilterOverrideDialog({ scope, scopeId, label, onClose, onChanged }: FilterOverrideDialogProps): JSX.Element {
  const [view, setView] = useState<LevelFilterView | null>(null);
  const [draft, setDraft] = useState<LevelFilter | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getLevelFilter(scope, scopeId)
      .then((loaded) => {
        setView(loaded);
        setDraft({ levels: loaded.levels, include_unleveled: loaded.include_unleveled, mwe_mode: loaded.mwe_mode });
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось загрузить настройки."));
  }, [scope, scopeId]);

  async function save(): Promise<void> {
    if (!draft) {
      return;
    }
    try {
      onChanged(await saveLevelFilter(scope, draft, scopeId));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить.");
    }
  }

  async function reset(): Promise<void> {
    try {
      onChanged(await resetLevelFilter(scope, scopeId));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сбросить.");
    }
  }

  return (
    <Dialog title={`Свои настройки: ${label}`} onClose={onClose}>
      {view && <p className="ql-muted">Источник: {SOURCE_LABELS[view.source]}.</p>}
      {draft ? <LevelFilterEditor value={draft} onChange={setDraft} /> : <p className="ql-muted">Загрузка…</p>}
      {error && <p className="ql-error">{error}</p>}
      <div className="ql-row ql-row--end">
        {view?.source === scope && (
          <button type="button" className="ql-button ql-button--ghost" onClick={() => void reset()}>
            Сбросить к общим
          </button>
        )}
        <button type="button" className="ql-button ql-button--ghost" onClick={onClose}>
          Отмена
        </button>
        <button type="button" className="ql-button ql-button--primary" onClick={() => void save()} disabled={!draft}>
          Сохранить
        </button>
      </div>
    </Dialog>
  );
}
