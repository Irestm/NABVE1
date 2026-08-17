import { useEffect, useRef, useState } from "react";
import { getProfileFact, listCommunicationStyles, setProfileFact } from "../api/client";
import type { CommunicationStyle } from "../types";
import "./PersonalityPanel.css";

// Matches modules/user_profile/domain.py's COMMUNICATION_STYLE_KEY/
// BREATH_EFFECT_KEY/DELAY_EFFECT_ENABLED_KEY/DELAY_SECONDS_KEY/
// VOICE_FX_MODE_KEY/ASSISTANT_VOLUME_KEY/CONFIRMATION_PHRASE_ENABLED_KEY
// string values exactly - these are
// stable, already-established fact keys, not something this panel invents.
// (assistant_name lives in components/SettingsPanel.tsx's "Профиль" tab;
// стоп-слово/активационная фраза/фразы трея moved to
// components/CustomCommandsPanel.tsx's "Системные команды" section, so
// they're no longer read/written here.)
const COMMUNICATION_STYLE_KEY = "communication_style";
const BREATH_EFFECT_KEY = "breath_effect_enabled";
const DELAY_EFFECT_ENABLED_KEY = "delay_effect_enabled";
const DELAY_SECONDS_KEY = "delay_seconds";
const VOICE_FX_MODE_KEY = "voice_fx_mode";
const CONFIRMATION_PHRASE_ENABLED_KEY = "confirmation_phrase_enabled";
const ASSISTANT_VOLUME_KEY = "assistant_volume";
const DEFAULT_DELAY_SECONDS = "0.3";
const DEFAULT_ASSISTANT_VOLUME = 100;
type VoiceFxMode = "none" | "tunnel" | "robotic";
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

  const [breathEffect, setBreathEffect] = useState(false);
  const [savingBreathEffect, setSavingBreathEffect] = useState(false);

  const [delayEffect, setDelayEffect] = useState(false);
  const [delaySeconds, setDelaySeconds] = useState(DEFAULT_DELAY_SECONDS);
  const [savingDelayEffect, setSavingDelayEffect] = useState(false);

  const [voiceFxMode, setVoiceFxMode] = useState<VoiceFxMode>("none");
  const [savingVoiceFxMode, setSavingVoiceFxMode] = useState(false);

  const [confirmationPhrase, setConfirmationPhrase] = useState(false);
  const [savingConfirmationPhrase, setSavingConfirmationPhrase] = useState(false);

  const [assistantVolume, setAssistantVolume] = useState(DEFAULT_ASSISTANT_VOLUME);
  const [savingAssistantVolume, setSavingAssistantVolume] = useState(false);

  const [error, setError] = useState<string>("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    // On a fresh launch this effect fires the moment the renderer's JS
    // executes, which can beat the backend's ~1-2s uvicorn+plugin startup
    // (see core.watchdog.supervisor) to the punch — the request lands while
    // the port isn't listening yet. App.tsx's own /api/status poll shrugs
    // this off by retrying every 1.5s forever; this effect used to run
    // once and give up permanently on that single early failure, showing
    // "Не удалось загрузить настройки личности." even though the very next
    // attempt would have succeeded. Retry a bounded number of times instead
    // of forever, since a real (non-startup) failure should still surface.
    const MAX_ATTEMPTS = 5;
    const RETRY_DELAY_MS = 1000;

    async function load(): Promise<void> {
      attempt += 1;
      try {
        const [availableStyles, style, breath, delayOn, delaySecondsFact, fxMode, volume, confirmPhrase] =
          await Promise.all([
            listCommunicationStyles(),
            getProfileFact(COMMUNICATION_STYLE_KEY),
            getProfileFact(BREATH_EFFECT_KEY),
            getProfileFact(DELAY_EFFECT_ENABLED_KEY),
            getProfileFact(DELAY_SECONDS_KEY),
            getProfileFact(VOICE_FX_MODE_KEY),
            getProfileFact(ASSISTANT_VOLUME_KEY),
            getProfileFact(CONFIRMATION_PHRASE_ENABLED_KEY),
          ]);
        if (cancelled) {
          return;
        }
        setStyles(availableStyles);
        setSelectedStyles(parseStyleKeys(style));
        setBreathEffect(breath === "1");
        setDelayEffect(delayOn === "1");
        setDelaySeconds(delaySecondsFact ?? DEFAULT_DELAY_SECONDS);
        setVoiceFxMode(fxMode === "tunnel" || fxMode === "robotic" ? fxMode : "none");
        setConfirmationPhrase(confirmPhrase === "1");
        const parsedVolume = volume ? Number(volume) : DEFAULT_ASSISTANT_VOLUME;
        setAssistantVolume(Number.isFinite(parsedVolume) ? parsedVolume : DEFAULT_ASSISTANT_VOLUME);
        setLoaded(true);
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (attempt < MAX_ATTEMPTS) {
          setTimeout(() => void load(), RETRY_DELAY_MS);
          return;
        }
        console.error("Failed to load personality settings:", error);
        setError("Не удалось загрузить настройки личности.");
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

  async function handleToggleDelayEffect(): Promise<void> {
    const next = !delayEffect;
    setSavingDelayEffect(true);
    setError("");
    try {
      await setProfileFact(DELAY_EFFECT_ENABLED_KEY, next ? "1" : "0");
      setDelayEffect(next);
    } catch (error) {
      console.error("Failed to save the delay-effect setting:", error);
      setError("Не удалось сохранить настройку задержки.");
    } finally {
      setSavingDelayEffect(false);
    }
  }

  async function handleSaveDelaySeconds(): Promise<void> {
    const clamped = Math.min(3.0, Math.max(0.3, Number(delaySeconds) || 0.3));
    const value = clamped.toFixed(1);
    setDelaySeconds(value);
    try {
      await setProfileFact(DELAY_SECONDS_KEY, value);
    } catch (error) {
      console.error("Failed to save the delay duration:", error);
      setError("Не удалось сохранить длительность задержки.");
    }
  }

  async function handleToggleConfirmationPhrase(): Promise<void> {
    const next = !confirmationPhrase;
    setSavingConfirmationPhrase(true);
    setError("");
    try {
      await setProfileFact(CONFIRMATION_PHRASE_ENABLED_KEY, next ? "1" : "0");
      setConfirmationPhrase(next);
    } catch (error) {
      console.error("Failed to save the confirmation-phrase setting:", error);
      setError("Не удалось сохранить настройку подтверждения.");
    } finally {
      setSavingConfirmationPhrase(false);
    }
  }

  async function handleVoiceFxModeChange(mode: VoiceFxMode): Promise<void> {
    setSavingVoiceFxMode(true);
    setError("");
    try {
      await setProfileFact(VOICE_FX_MODE_KEY, mode);
      setVoiceFxMode(mode);
    } catch (error) {
      console.error("Failed to save the voice-fx setting:", error);
      setError("Не удалось сохранить голосовой эффект.");
    } finally {
      setSavingVoiceFxMode(false);
    }
  }

  const volumeSaveTimeout = useRef<number | null>(null);

  function handleAssistantVolumeChange(value: number): void {
    setAssistantVolume(value);
    if (volumeSaveTimeout.current !== null) {
      window.clearTimeout(volumeSaveTimeout.current);
    }
    volumeSaveTimeout.current = window.setTimeout(() => {
      setSavingAssistantVolume(true);
      setProfileFact(ASSISTANT_VOLUME_KEY, String(value))
        .catch((error) => {
          console.error("Failed to save the assistant volume:", error);
          setError("Не удалось сохранить громкость.");
        })
        .finally(() => setSavingAssistantVolume(false));
    }, 300);
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

        <label className="personality-panel__checkbox">
          <input
            type="checkbox"
            checked={delayEffect}
            disabled={savingDelayEffect}
            onChange={() => void handleToggleDelayEffect()}
          />
          Затяжка в ответе
        </label>

        <label className="personality-panel__checkbox">
          <input
            type="checkbox"
            checked={confirmationPhrase}
            disabled={savingConfirmationPhrase}
            onChange={() => void handleToggleConfirmationPhrase()}
          />
          Подтверждение перед выполнением (Да, сэр / Да, мэм)
        </label>
        <p className="status-detail">Фраза зависит от пола, указанного в профиле</p>
        {delayEffect && (
          <div className="row personality-panel__delay-row">
            <input
              type="number"
              min={0.3}
              max={3.0}
              step={0.1}
              value={delaySeconds}
              onChange={(event) => setDelaySeconds(event.target.value)}
              onBlur={() => void handleSaveDelaySeconds()}
            />
            <span className="personality-panel__unit">сек</span>
          </div>
        )}

        <div className="personality-panel__radio-group">
          <label className="personality-panel__radio">
            <input
              type="radio"
              name="voice-fx-mode"
              checked={voiceFxMode === "none"}
              disabled={savingVoiceFxMode}
              onChange={() => void handleVoiceFxModeChange("none")}
            />
            Без эффекта
          </label>
          <label className="personality-panel__radio">
            <input
              type="radio"
              name="voice-fx-mode"
              checked={voiceFxMode === "tunnel"}
              disabled={savingVoiceFxMode}
              onChange={() => void handleVoiceFxModeChange("tunnel")}
            />
            Голос как в тоннеле
          </label>
          <label className="personality-panel__radio">
            <input
              type="radio"
              name="voice-fx-mode"
              checked={voiceFxMode === "robotic"}
              disabled={savingVoiceFxMode}
              onChange={() => void handleVoiceFxModeChange("robotic")}
            />
            Роботизированный голос
          </label>
        </div>
      </div>

      <div className="personality-panel__field">
        <span className="personality-panel__label">Громкость голоса NABVE</span>
        <div className="row">
          <input
            type="range"
            min={0}
            max={100}
            value={assistantVolume}
            disabled={savingAssistantVolume}
            onChange={(event) => handleAssistantVolumeChange(Number(event.target.value))}
          />
          <span className="personality-panel__unit">{assistantVolume}%</span>
        </div>
      </div>
    </div>
  );
}
