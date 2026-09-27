import { useState } from "react";
import type { Direction, LearnMode, LearnSettings } from "../../api/english";
import { Dialog } from "./Dialog";

interface LearnSettingsDialogProps {
  settings: LearnSettings;
  onSave: (settings: LearnSettings) => void;
  onClose: () => void;
}

const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: "en_ru", label: "EN → RU" },
  { value: "ru_en", label: "RU → EN" },
];

const MODES: { value: LearnMode; label: string; hint: string }[] = [
  { value: "mixed", label: "Смешанный", hint: "Сначала выбор из вариантов, потом ввод" },
  { value: "choice", label: "Только выбор", hint: "4 варианта ответа" },
  { value: "input", label: "Только ввод", hint: "Пишете перевод сами" },
];

export function LearnSettingsDialog({ settings, onSave, onClose }: LearnSettingsDialogProps): JSX.Element {
  const [draft, setDraft] = useState<LearnSettings>(settings);

  return (
    <Dialog title="Настройки заучивания" onClose={onClose}>
      <label className="ql-toggle-row">
        <span>
          <span className="ql-toggle-row__title">Перемешивать карточки</span>
        </span>
        <input
          type="checkbox"
          className="ql-switch"
          checked={draft.shuffle}
          onChange={(event) => setDraft({ ...draft, shuffle: event.target.checked })}
        />
      </label>

      <fieldset className="ql-fieldset">
        <legend className="ql-toggle-row__title">Показывать реплику из серии</legend>
        <label className="ql-toggle-row">
          <span className="ql-toggle-row__title">Для выражений</span>
          <input
            type="checkbox"
            className="ql-switch"
            checked={draft.contextForExpressions}
            onChange={(event) => setDraft({ ...draft, contextForExpressions: event.target.checked })}
          />
        </label>
        <label className="ql-toggle-row">
          <span className="ql-toggle-row__title">Для слов</span>
          <input
            type="checkbox"
            className="ql-switch"
            checked={draft.contextForWords}
            onChange={(event) => setDraft({ ...draft, contextForWords: event.target.checked })}
          />
        </label>
      </fieldset>

      <fieldset className="ql-fieldset">
        <legend className="ql-toggle-row__title">Направление</legend>
        <div className="ql-segmented">
          {DIRECTIONS.map((item) => (
            <button
              key={item.value}
              type="button"
              className={draft.direction === item.value ? "ql-segmented__item ql-segmented__item--active" : "ql-segmented__item"}
              aria-pressed={draft.direction === item.value}
              onClick={() => setDraft({ ...draft, direction: item.value })}
            >
              {item.label}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="ql-fieldset">
        <legend className="ql-toggle-row__title">Типы заданий</legend>
        {MODES.map((item) => (
          <label key={item.value} className="ql-radio">
            <input
              type="radio"
              name="learn-mode"
              checked={draft.mode === item.value}
              onChange={() => setDraft({ ...draft, mode: item.value })}
            />
            <span>
              <span className="ql-toggle-row__title">{item.label}</span>
              <span className="ql-muted ql-radio__hint">{item.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="ql-row ql-row--end">
        <button type="button" className="ql-button ql-button--ghost" onClick={onClose}>
          Отмена
        </button>
        <button type="button" className="ql-button ql-button--primary" onClick={() => onSave(draft)}>
          Сохранить
        </button>
      </div>
    </Dialog>
  );
}
