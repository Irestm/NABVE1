import { useEffect, useRef, useState } from "react";
import { getVoiceOptions, selectVoice, speak } from "../api/client";
import type { VoiceOption } from "../types";

const PREVIEW_PHRASE = "Теперь это мой голос";
const GENDER_LABELS: Record<VoiceOption["gender"], string> = {
  male: "мужской",
  female: "женский",
};

export function VoiceSettingsPanel(): JSX.Element | null {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [previewing, setPreviewing] = useState<string>("");
  const [error, setError] = useState<string>("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

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
    <div className="section voice-settings-panel">
      <h3>Голос ассистента</h3>
      {error && <p className="status-error">{error}</p>}
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
  );
}
