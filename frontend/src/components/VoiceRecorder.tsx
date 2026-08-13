import { useEffect, useRef, useState } from "react";
import { confirmCommand, sendVoiceConfirmation, sendVoiceQuery, speak } from "../api/client";
import type { VoiceQueryResponse } from "../types";

// Standard Web APIs only (MediaRecorder + getUserMedia): this works
// identically in Electron's renderer and in a plain phone browser, so no
// platform adapter is needed here — see frontend/src/platform/electronAdapter.ts
// for the rule on what *does* need one.

// Auto-stop-on-silence tuning: RMS is normalized 0..1 from 8-bit PCM samples.
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_DURATION_MS = 1200;
const MAX_RECORDING_MS = 30000;

// The real reply can take a while (STT + intent routing + a browser-automated
// AI provider round-trip). Playing one of these instantly covers that gap so
// a voice conversation doesn't go dead-silent while it's thinking. These are
// synthesized once via the same Piper voice as real replies and cached — the
// browser's own live speechSynthesis (espeak-ng on Linux) was tried first,
// but its voice is garbled/unintelligible and often has no Russian voice
// installed at all, so it either sounded wrong or said nothing.
const FILLER_PHRASES = ["Секунду, обрабатываю…", "Сейчас посмотрю…", "Одну минуту…", "Думаю…"];

// "ru"/"en" are the two quick-access toggle options; "uk" lives behind the
// "…" menu (matches core/voice/config.py's supported_languages), along with
// "auto" (null — Whisper's own language detection) for going back to it.
const LANGUAGE_LABELS: Record<string, string> = { ru: "RU", en: "EN", uk: "UK" };
const PRIMARY_LANGUAGES = ["ru", "en"];
const EXTRA_LANGUAGES = ["uk"];
const VOICE_LANGUAGE_STORAGE_KEY = "voiceLanguage";

function readStoredLanguage(): string | null {
  try {
    return window.localStorage.getItem(VOICE_LANGUAGE_STORAGE_KEY) ?? "ru";
  } catch (error) {
    console.error("Failed to read the stored voice language from localStorage:", error);
    return "ru";
  }
}

interface VoiceRecorderProps {
  // Lifts local mic/playback activity up to App so the shared CentralOrb /
  // VoiceWaveform (normally driven by the backend's polled assistant state,
  // which this thin-client request/response flow never touches) animates for
  // browser-side voice too, instead of staying stuck on "idle".
  onRecordingChange?: (recording: boolean) => void;
  onSpeakingChange?: (speaking: boolean) => void;
}

function rms(data: Uint8Array): number {
  let sumSquares = 0;
  for (let i = 0; i < data.length; i += 1) {
    const normalized = (data[i] - 128) / 128;
    sumSquares += normalized * normalized;
  }
  return Math.sqrt(sumSquares / data.length);
}

export function VoiceRecorder({ onRecordingChange, onSpeakingChange }: VoiceRecorderProps): JSX.Element {
  // `active` toggles the whole real-time conversation on/off; there is no
  // separate per-utterance "stop" control — each turn stops itself once the
  // mic level drops below SILENCE_RMS_THRESHOLD for SILENCE_DURATION_MS, and
  // the reply's playback ending automatically re-arms the mic for the next
  // turn, for as long as the conversation stays active.
  const [active, setActive] = useState(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [result, setResult] = useState<VoiceQueryResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [voiceLanguage, setVoiceLanguage] = useState<string | null>(readStoredLanguage);
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

  // Mirrors `active` for use inside async callbacks (recorder.onstop,
  // audio.onended) where a stale closure over the state value would keep the
  // loop going after the user already ended the conversation.
  const activeRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  // Acquired once per conversation (see ensureStream) and reused for every
  // turn's MediaRecorder instead of calling getUserMedia again each time.
  // Regression: re-requesting the mic on every single turn (including the
  // turn right after a confirmation question) adds real browser-level
  // negotiation latency before recording actually starts, clipping the
  // start of whatever the user says the moment they see/hear the prompt -
  // exactly the "only works on the 2nd try" pattern, since a stream that's
  // already open has none of that delay.
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const inputContextRef = useRef<AudioContext | null>(null);
  const silenceWatcherRef = useRef<number | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  // Set by startSilenceWatcher the moment mic level crosses the speech
  // threshold at least once during the current turn; recorder.onstop reads
  // it to tell "user paused after speaking" (send it) apart from "nothing
  // was ever said, MAX_RECORDING_MS just ran out" (pause quietly instead —
  // see point 5: it used to send that silence to the server anyway, which
  // came back as a spoken "не поняла команду" nag with nobody talking).
  const hadSpeechRef = useRef(false);
  // Set right after a confirmation_required reply, cleared once resolved
  // (by voice or by the Подтвердить/Отмена buttons). The turn that follows
  // a confirmation question is the user's spoken yes/no answer, not a new
  // command - without tracking this, that recording used to go through
  // sendVoiceQuery like any other turn, where a bare "да" matches no
  // command and isn't a real question either, so it came back as a
  // generic "не поняла команду" and the pending confirmation was never
  // actually resolved.
  const pendingConfirmTokenRef = useRef<string | null>(null);
  const fillerCacheRef = useRef<string[]>([]);
  const fillerAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const clips = await Promise.all(FILLER_PHRASES.map((text) => speak(text, "ru")));
        if (!cancelled) {
          fillerCacheRef.current = clips
            .map((clip) => clip.audio_wav_base64)
            .filter((base64): base64 is string => Boolean(base64));
        }
      } catch (error) {
        // Best-effort: playFiller() just no-ops if this never populates.
        console.error("Failed to pre-synthesize filler phrases:", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    onRecordingChange?.(recording);
  }, [recording, onRecordingChange]);

  useEffect(() => {
    onSpeakingChange?.(speaking);
  }, [speaking, onSpeakingChange]);

  useEffect(() => {
    return () => {
      activeRef.current = false;
      stopSilenceWatcher();
      stopPlayback();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      releaseStream();
    };
  }, []);

  function stopSilenceWatcher(): void {
    if (silenceWatcherRef.current !== null) {
      window.clearInterval(silenceWatcherRef.current);
      silenceWatcherRef.current = null;
    }
    void inputContextRef.current?.close();
    inputContextRef.current = null;
    setMicLevel(0);
  }

  function startSilenceWatcher(stream: MediaStream): void {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    inputContextRef.current = audioContext;

    const data = new Uint8Array(analyser.fftSize);
    let hasSpoken = false;
    let lastVoiceAt = Date.now();
    const startedAt = Date.now();
    hadSpeechRef.current = false;

    silenceWatcherRef.current = window.setInterval(() => {
      analyser.getByteTimeDomainData(data);
      const level = rms(data);
      setMicLevel(level);
      const now = Date.now();

      if (level > SILENCE_RMS_THRESHOLD) {
        hasSpoken = true;
        hadSpeechRef.current = true;
        lastVoiceAt = now;
      }

      if (hasSpoken && now - lastVoiceAt > SILENCE_DURATION_MS) {
        stopSilenceWatcher();
        mediaRecorderRef.current?.stop();
      } else if (now - startedAt > MAX_RECORDING_MS) {
        stopSilenceWatcher();
        mediaRecorderRef.current?.stop();
      }
    }, 100);
  }

  function stopFiller(): void {
    if (fillerAudioRef.current) {
      fillerAudioRef.current.onended = null;
      fillerAudioRef.current.pause();
      fillerAudioRef.current = null;
    }
  }

  function playFiller(): void {
    const clips = fillerCacheRef.current;
    if (clips.length === 0) {
      return;
    }
    const base64 = clips[Math.floor(Math.random() * clips.length)];
    const audio = new Audio(`data:audio/wav;base64,${base64}`);
    fillerAudioRef.current = audio;
    audio.onended = () => {
      if (fillerAudioRef.current === audio) {
        fillerAudioRef.current = null;
      }
    };
    void audio.play();
  }

  function stopPlayback(): void {
    if (currentAudioRef.current) {
      currentAudioRef.current.onended = null;
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    setSpeaking(false);
  }

  function playReply(base64: string): void {
    stopFiller();
    stopPlayback();
    const audio = new Audio(`data:audio/wav;base64,${base64}`);
    currentAudioRef.current = audio;
    audio.onended = () => {
      stopPlayback();
      if (activeRef.current) {
        void startTurn();
      }
    };
    setSpeaking(true);
    void audio.play();
  }

  function releaseStream(): void {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }

  async function ensureStream(): Promise<MediaStream | null> {
    if (streamRef.current) {
      return streamRef.current;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Микрофон недоступен в этом браузере.");
      return null;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      return stream;
    } catch (error) {
      console.error("Failed to acquire the microphone stream:", error);
      setError("Не удалось получить доступ к микрофону.");
      return null;
    }
  }

  async function startTurn(): Promise<void> {
    if (!activeRef.current) {
      return;
    }
    setError("");
    const stream = await ensureStream();
    if (!stream) {
      endConversation();
      return;
    }
    if (!activeRef.current) {
      return;
    }
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };
    recorder.onstop = () => {
      stopSilenceWatcher();
      setRecording(false);
      if (!activeRef.current) {
        return;
      }
      if (!hadSpeechRef.current) {
        // MAX_RECORDING_MS safety net fired with nothing ever said — point
        // 5: don't round-trip pure silence to the server just to have it
        // read "не поняла команду" back at nobody. Pause quietly instead.
        pauseForSilence();
        return;
      }
      void handleRecordingComplete(new Blob(chunksRef.current, { type: recorder.mimeType }));
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setRecording(true);
    startSilenceWatcher(stream);
  }

  function startConversation(): void {
    setError("");
    setNote("");
    setResult(null);
    pendingConfirmTokenRef.current = null;
    activeRef.current = true;
    setActive(true);
    void startTurn();
  }

  function endConversation(): void {
    activeRef.current = false;
    setActive(false);
    pendingConfirmTokenRef.current = null;
    stopSilenceWatcher();
    stopPlayback();
    stopFiller();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    releaseStream();
    setRecording(false);
  }

  function pauseForSilence(): void {
    activeRef.current = false;
    setActive(false);
    releaseStream();
    setNote("Не услышал речь — разговор на паузе.");
  }

  async function handleRecordingComplete(blob: Blob): Promise<void> {
    setBusy(true);
    setError("");
    setNote("");
    playFiller();
    const pendingToken = pendingConfirmTokenRef.current;
    try {
      const response = pendingToken
        ? await sendVoiceConfirmation(blob, pendingToken, "confirm.webm", voiceLanguage)
        : await sendVoiceQuery(blob, "query.webm", voiceLanguage);
      pendingConfirmTokenRef.current =
        response.status === "confirmation_required" && response.token ? response.token : null;
      setResult(response);
      if (response.audio_wav_base64) {
        playReply(response.audio_wav_base64);
      } else if (activeRef.current) {
        stopFiller();
        void startTurn();
      }
    } catch (error) {
      console.error("Failed to process a voice turn:", error);
      stopFiller();
      setError("Нет связи с ядром ассистента.");
      endConversation();
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(approved: boolean): Promise<void> {
    if (!result?.token) {
      return;
    }
    pendingConfirmTokenRef.current = null;
    setBusy(true);
    try {
      const response = await confirmCommand(result.token, approved);
      setResult({ ...result, reply_text: response.message, status: response.status, token: null });
      const spoken = await speak(response.message, result.language);
      if (spoken.audio_wav_base64) {
        playReply(spoken.audio_wav_base64);
      }
    } catch (error) {
      console.error("Failed to confirm a pending voice command:", error);
      setError("Нет связи с ядром ассистента.");
    } finally {
      setBusy(false);
    }
  }

  // sqrt compresses the range so quiet speech still visibly moves the
  // indicator instead of the scale staying flat until near-shouting volume.
  const meterFraction = Math.min(1, Math.sqrt(micLevel) * 2.2);

  return (
    <div className="section voice-recorder">
      <h3>Голосовой ввод</h3>

      <div className="row voice-lang-toggle">
        {PRIMARY_LANGUAGES.map((lang) => (
          <button
            key={lang}
            className={voiceLanguage === lang ? "active" : ""}
            onClick={() => selectLanguage(lang)}
          >
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
            <button
              key={lang}
              className={voiceLanguage === lang ? "active" : ""}
              onClick={() => selectLanguage(lang)}
            >
              {LANGUAGE_LABELS[lang]}
            </button>
          ))}
        </div>
      )}

      {recording && (
        <div className="voice-level" aria-hidden="true">
          <div className="voice-level__ring" style={{ transform: `scale(${1 + meterFraction * 1.6})` }} />
          <div className="voice-level__core" style={{ transform: `scale(${1 + meterFraction * 0.9})` }} />
        </div>
      )}

      <div className="row">
        <button className={active ? "danger" : ""} onClick={() => (active ? endConversation() : startConversation())}>
          {active ? "Завершить разговор" : "Начать разговор"}
        </button>
      </div>

      {recording && <p className="status-detail">Слушаю — отправлю, как только вы замолчите</p>}
      {busy && <p className="status-detail">Обрабатываю…</p>}
      {speaking && <p className="status-detail">Ассистент отвечает…</p>}
      {note && <p className="status-detail">{note}</p>}

      {error && <p className="status-error">{error}</p>}
      {result && (
        <div className="voice-result">
          {result.transcribed_text && <p className="voice-transcript">«{result.transcribed_text}»</p>}
          <p className="last-message">{result.reply_text}</p>
          {result.status === "confirmation_required" && result.token && (
            <div className="row">
              <button className="danger" disabled={busy} onClick={() => void handleConfirm(true)}>
                Подтвердить
              </button>
              <button disabled={busy} onClick={() => void handleConfirm(false)}>
                Отмена
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
