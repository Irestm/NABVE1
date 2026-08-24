import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { getProfileFact, getVoiceOptions, selectVoice, setProfileFact, speak } from "../api/client";
import { readStoredVoiceLanguage, VOICE_LANGUAGE_STORAGE_KEY } from "./VoiceRecorder";
import type { VoiceOption } from "../types";

const PREVIEW_PHRASE = "Теперь это мой голос";
const GENDER_LABELS: Record<VoiceOption["gender"], string> = {
  male: "мужской",
  female: "женский",
};

// Matches modules/user_profile/domain.py's ASSISTANT_VOLUME_KEY exactly —
// moved here from components/PersonalityPanel.tsx as of the 2026-08-24
// redesign ("громкость" now groups with "голос" in Settings).
const ASSISTANT_VOLUME_KEY = "assistant_volume";
const DEFAULT_ASSISTANT_VOLUME = 100;

// "ru"/"en" are the two quick-access toggle options; "uk" lives behind the
// "…" menu (matches core/voice/config.py's supported_languages), along with
// "auto" (null — Whisper's own language detection) for going back to it.
// Moved here from components/VoiceRecorder.tsx as of the 2026-08-24 redesign
// — VoiceRecorder now just reads the persisted choice (see
// readStoredVoiceLanguage), this is the only place it's actually picked.
const LANGUAGE_LABELS: Record<string, string> = { ru: "RU", en: "EN", uk: "UK" };
const PRIMARY_LANGUAGES = ["ru", "en"];
const EXTRA_LANGUAGES = ["uk"];

export function VoiceSettingsPanel(): JSX.Element | null {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [previewing, setPreviewing] = useState<string>("");
  const [error, setError] = useState<string>("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [assistantVolume, setAssistantVolume] = useState(DEFAULT_ASSISTANT_VOLUME);
  const [savingAssistantVolume, setSavingAssistantVolume] = useState(false);
  const volumeSaveTimeout = useRef<number | null>(null);

  const [voiceLanguage, setVoiceLanguage] = useState<string | null>(readStoredVoiceLanguage);
  const [showMoreLanguages, setShowMoreLanguages] = useState(false);

  function selectLanguage(lang: string | null): void {
    setVoiceLanguage(lang);
    setShowMoreLanguages(false);
    try {
      if (lang) {
        window.localStorage.setItem(VOICE_LANGUAGE_STORAGE_KEY, lang);
      } else {
        window.localStorage.removeItem(VOICE_LANGUAGE_STORAGE_KEY);
      }
    } catch (error) {
      // localStorage can be unavailable (e.g. private browsing) — selection
      // still works for the session, it just won't be remembered.
      console.error("Failed to persist the selected voice language to localStorage:", error);
    }
  }

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

  useEffect(() => {
    let cancelled = false;
    getProfileFact(ASSISTANT_VOLUME_KEY)
      .then((volume) => {
        if (cancelled) {
          return;
        }
        const parsed = volume ? Number(volume) : DEFAULT_ASSISTANT_VOLUME;
        setAssistantVolume(Number.isFinite(parsed) ? parsed : DEFAULT_ASSISTANT_VOLUME);
      })
      .catch((error) => {
        console.error("Failed to load the assistant volume:", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    // This effect fires the moment the renderer's JS executes, which can
    // beat the backend's ~1-2s uvicorn+plugin startup (see
    // core.watchdog.supervisor) to the punch — see App.tsx's own
    // /api/status poll, which shrugs off the same race by retrying every
    // 1.5s forever. This effect used to run once and give up permanently
    // on that single early failure. Retry a bounded number of times
    // instead of forever, since a real (non-startup) failure should still
    // surface.
    const MAX_ATTEMPTS = 5;
    const RETRY_DELAY_MS = 1000;

    async function load(): Promise<void> {
      attempt += 1;
      try {
        const options = await getVoiceOptions();
        if (!cancelled) {
          setVoices(options.voices);
          setSelected(options.selected);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (attempt < MAX_ATTEMPTS) {
          setTimeout(() => void load(), RETRY_DELAY_MS);
          return;
        }
        console.error("Failed to load voice options:", error);
        setError("Не удалось загрузить список голосов.");
      }
    }

    void load();
    return () => {
      cancelled = true;
      audioRef.current?.pause();
    };
  }, []);

  async function handlePreview(speaker: string): Promise<void> {
    audioRef.current?.pause();
    setError("");
    setPreviewing(speaker);
    try {
      const response = await speak(PREVIEW_PHRASE, "ru", speaker);
      if (!response.audio_wav_base64) {
        setError("Синтез речи недоступен.");
        setPreviewing("");
        return;
      }
      const audio = new Audio(`data:audio/wav;base64,${response.audio_wav_base64}`);
      audioRef.current = audio;
      audio.onended = () => setPreviewing("");
      await audio.play();
    } catch (error) {
      console.error("Failed to preview a voice:", error);
      setError("Не удалось воспроизвести превью голоса.");
      setPreviewing("");
    }
  }

  async function handleSelect(speaker: string): Promise<void> {
    setError("");
    try {
      const response = await selectVoice(speaker);
      setSelected(response.selected);
    } catch (error) {
      console.error("Failed to save the selected voice:", error);
      setError("Не удалось сохранить выбор голоса.");
    }
  }

  return (
    <div className="voice-settings-panel">
      {error && <p className="status-error">{error}</p>}

      <div className="settings-panel__field">
        <span className="settings-panel__label">Язык распознавания</span>
        <div className="row voice-lang-toggle">
          {PRIMARY_LANGUAGES.map((lang) => (
            <button key={lang} className={voiceLanguage === lang ? "active" : ""} onClick={() => selectLanguage(lang)}>
              {LANGUAGE_LABELS[lang]}
            </button>
          ))}
          <button
            className={showMoreLanguages ? "active" : ""}
            aria-label="Другие языки"
            onClick={() => setShowMoreLanguages((value) => !value)}
          >
            ⋯
          </button>
        </div>
        {showMoreLanguages && (
          <div className="row voice-lang-toggle">
            <button className={voiceLanguage === null ? "active" : ""} onClick={() => selectLanguage(null)}>
              Авто
            </button>
            {EXTRA_LANGUAGES.map((lang) => (
              <button key={lang} className={voiceLanguage === lang ? "active" : ""} onClick={() => selectLanguage(lang)}>
                {LANGUAGE_LABELS[lang]}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="settings-panel__field">
        <span className="settings-panel__label">Громкость голоса NABVE</span>
        <div className="row">
          <input
            type="range"
            min={0}
            max={100}
            value={assistantVolume}
            disabled={savingAssistantVolume}
            onChange={(event) => handleAssistantVolumeChange(Number(event.target.value))}
            style={{ "--range-fill": `${assistantVolume}%` } as CSSProperties}
          />
          <span className="personality-panel__unit">{assistantVolume}%</span>
        </div>
      </div>

      <div className="settings-panel__field">
        <span className="settings-panel__label">Голос ассистента</span>
        {voices.length === 0 && !error && <p className="status-detail">Загрузка голосов…</p>}
        <div className="voice-options">
        {voices.map((voice) => (
          <div
            key={voice.speaker}
            className={`voice-option${selected === voice.speaker ? " voice-option--selected" : ""}`}
          >
            <div className="voice-option__info">
              <span className="voice-option__label">{voice.label}</span>
              <span className="voice-option__gender">{GENDER_LABELS[voice.gender]}</span>
            </div>
            <div className="row">
              <button
                type="button"
                onClick={() => void handlePreview(voice.speaker)}
                disabled={previewing === voice.speaker}
              >
                {previewing === voice.speaker ? "Звучит…" : "Превью"}
              </button>
              <button
                type="button"
                className={selected === voice.speaker ? "voice-option__select active" : "voice-option__select"}
                onClick={() => void handleSelect(voice.speaker)}
                disabled={selected === voice.speaker}
              >
                {selected === voice.speaker ? "Выбран" : "Выбрать"}
              </button>
            </div>
          </div>
        ))}
        </div>
      </div>
    </div>
  );
}
