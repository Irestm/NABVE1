import { useEffect, useState } from "react";
import { getProfileFact, listCommunicationStyles, setProfileFact } from "../api/client";
import type { CommunicationStyle } from "../types";
import "./PersonalityPanel.css";

// Matches modules/user_profile/domain.py's COMMUNICATION_STYLE_KEY/
// STOP_WORD_KEY/BREATH_EFFECT_KEY string values exactly - these are stable,
// already-established fact keys, not something this panel invents.
// (assistant_name lives in components/SettingsPanel.tsx's "Профиль" tab now.)
const COMMUNICATION_STYLE_KEY = "communication_style";
const STOP_WORD_KEY = "stop_word";
const BREATH_EFFECT_KEY = "breath_effect_enabled";
const DEFAULT_STYLE_KEY = "polite";
// Matches modules/user_profile/communication_styles.py's MAX_SELECTED_STYLES.
const MAX_SELECTED_STYLES = 3;

function describeIntonation(rate: number): string {
  if (rate > 1.02) {
    return "быстрее и выше";
  }
  if (rate < 0.98) {
    return "медленнее и ниже";
  }
  return "обычный темп";
}

function parseStyleKeys(raw: string | null): string[] {
  if (!raw) {
    return [DEFAULT_STYLE_KEY];
  }
  const keys = raw
    .split(",")
    .map((key) => key.trim())
    .filter(Boolean);
  return keys.length > 0 ? keys : [DEFAULT_STYLE_KEY];
}

export function PersonalityPanel(): JSX.Element {
  const [styles, setStyles] = useState<CommunicationStyle[]>([]);
  const [selectedStyles, setSelectedStyles] = useState<string[]>([DEFAULT_STYLE_KEY]);
  const [savingStyles, setSavingStyles] = useState(false);

  const [stopWord, setStopWord] = useState<string>("");
  const [stopWordInput, setStopWordInput] = useState<string>("");

  const [breathEffect, setBreathEffect] = useState(false);
  const [savingBreathEffect, setSavingBreathEffect] = useState(false);

  const [error, setError] = useState<string>("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [availableStyles, style, word, breath] = await Promise.all([
          listCommunicationStyles(),
          getProfileFact(COMMUNICATION_STYLE_KEY),
          getProfileFact(STOP_WORD_KEY),
          getProfileFact(BREATH_EFFECT_KEY),
        ]);
        if (cancelled) {
          return;
        }
        setStyles(availableStyles);
        setSelectedStyles(parseStyleKeys(style));
        setStopWord(word ?? "");
        setStopWordInput(word ?? "");
        setBreathEffect(breath === "1");
        setLoaded(true);
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load personality settings:", error);
          setError("Не удалось загрузить настройки личности.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleToggleStyle(key: string): Promise<void> {
    const isSelected = selectedStyles.includes(key);
    if (!isSelected && selectedStyles.length >= MAX_SELECTED_STYLES) {
      return;
    }
    const next = isSelected ? selectedStyles.filter((selected) => selected !== key) : [...selectedStyles, key];
    const toSave = next.length > 0 ? next : [DEFAULT_STYLE_KEY];

    setSavingStyles(true);
    setError("");
    try {
      await setProfileFact(COMMUNICATION_STYLE_KEY, toSave.join(","));
      setSelectedStyles(toSave);
    } catch (error) {
      console.error("Failed to save the communication style:", error);
      setError("Не удалось сохранить стиль общения.");
    } finally {
      setSavingStyles(false);
    }
  }

  async function handleSaveStopWord(): Promise<void> {
    const trimmed = stopWordInput.trim();
    if (!trimmed) {
      return;
    }
    try {
      await setProfileFact(STOP_WORD_KEY, trimmed);
      setStopWord(trimmed);
    } catch (error) {
      console.error("Failed to save the stop word:", error);
      setError("Не удалось сохранить стоп-слово.");
    }
  }

  async function handleToggleBreathEffect(): Promise<void> {
    const next = !breathEffect;
    setSavingBreathEffect(true);
    setError("");
    try {
      await setProfileFact(BREATH_EFFECT_KEY, next ? "1" : "0");
      setBreathEffect(next);
    } catch (error) {
      console.error("Failed to save the breath-effect setting:", error);
      setError("Не удалось сохранить настройку звука.");
    } finally {
      setSavingBreathEffect(false);
    }
  }

  return (
    <div className="section personality-panel">
      <h3>Личность ассистента</h3>
      {error && <p className="status-error">{error}</p>}
      {!loaded && !error && <p className="status-detail">Загрузка…</p>}

      <div className="personality-panel__field">
        <span className="personality-panel__label">
          Стиль общения — можно смешать до {MAX_SELECTED_STYLES} черт ({selectedStyles.length}/{MAX_SELECTED_STYLES})
        </span>
        <div className="personality-panel__styles">
          {styles.map((style) => {
            const isActive = selectedStyles.includes(style.key);
            const atCap = !isActive && selectedStyles.length >= MAX_SELECTED_STYLES;
            return (
              <button
                key={style.key}
                type="button"
                className={`personality-panel__style${isActive ? " personality-panel__style--active" : ""}`}
                onClick={() => void handleToggleStyle(style.key)}
                disabled={savingStyles || atCap}
                title={`Интонация: ${describeIntonation(style.prosody_rate)}`}
              >
                {style.label}
              </button>
            );
          })}
        </div>
      </div>

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
        <span className="personality-panel__label">Звуковые эффекты</span>
        <label className="personality-panel__checkbox">
          <input
            type="checkbox"
            checked={breathEffect}
            disabled={savingBreathEffect}
            onChange={() => void handleToggleBreathEffect()}
          />
          Звук вдоха перед ответом
        </label>
      </div>
    </div>
  );
}
