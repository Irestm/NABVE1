import type { LevelFilter, MweMode, StoredLevel } from "../../api/english";
import { STORED_LEVELS } from "./levelFilter";

interface LevelFilterEditorProps {
  value: LevelFilter;
  onChange: (next: LevelFilter) => void;
}

const MWE_MODES: { value: MweMode; label: string }[] = [
  { value: "always", label: "Показывать все выражения всегда" },
  { value: "follow_levels", label: "Выражения подчиняются фильтру уровней" },
];

export function LevelFilterEditor({ value, onChange }: LevelFilterEditorProps): JSX.Element {
  function toggle(level: StoredLevel, checked: boolean): void {
    const levels = checked ? [...value.levels, level] : value.levels.filter((item) => item !== level);
    onChange({ ...value, levels: STORED_LEVELS.filter((item) => levels.includes(item)) });
  }

  return (
    <div className="ql-level-filter">
      <fieldset className="ql-fieldset">
        <legend className="ql-toggle-row__title">Уровни слов</legend>
        <div className="ql-level-filter__checks">
          {STORED_LEVELS.map((level) => (
            <label key={level} className="ql-check">
              <input
                type="checkbox"
                checked={value.levels.includes(level)}
                onChange={(event) => toggle(level, event.target.checked)}
              />
              <span>{level}</span>
            </label>
          ))}
          <label className="ql-check">
            <input
              type="checkbox"
              checked={value.include_unleveled}
              onChange={(event) => onChange({ ...value, include_unleveled: event.target.checked })}
            />
            <span>Без уровня</span>
          </label>
        </div>
      </fieldset>
      <fieldset className="ql-fieldset">
        <legend className="ql-toggle-row__title">Выражения</legend>
        {MWE_MODES.map((mode) => (
          <label key={mode.value} className="ql-radio">
            <input
              type="radio"
              name="mwe-mode"
              checked={value.mwe_mode === mode.value}
              onChange={() => onChange({ ...value, mwe_mode: mode.value })}
            />
            <span>
              <span className="ql-toggle-row__title">{mode.label}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
