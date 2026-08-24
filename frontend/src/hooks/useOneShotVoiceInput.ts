import { useRef, useState } from "react";
import { transcribeAudio } from "../api/client";

// Same RMS-over-silence-window idea as VoiceRecorder.tsx's own recorder, but
// deliberately NOT extracted out of that component and shared — VoiceRecorder
// drives a whole real-time conversation loop (filler phrases, barge-in,
// pending-confirmation tracking, central-orb hooks) that a one-shot
// mic-button filling a single text field has no business depending on.
// This is a smaller, independent implementation of just the "record until
// the user stops talking, then transcribe" part.
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_DURATION_MS = 1200;
const MAX_RECORDING_MS = 15000;
const WATCHER_INTERVAL_MS = 100;

function rms(data: Uint8Array): number {
  let sumSquares = 0;
  for (let i = 0; i < data.length; i += 1) {
    const normalized = (data[i] - 128) / 128;
    sumSquares += normalized * normalized;
  }
  return Math.sqrt(sumSquares / data.length);
}

interface UseOneShotVoiceInputResult {
  recording: boolean;
  error: string;
  start: () => void;
}

/**
 * Records from the mic until the user pauses (or MAX_RECORDING_MS elapses),
 * transcribes it via /api/voice/transcribe (text only — no intent
 * resolution or command dispatch, see that endpoint's docstring), and hands
 * the result to `onResult`. Meant for filling a single text field by voice,
 * not for a conversation.
 */
export function useOneShotVoiceInput(
  onResult: (text: string) => void,
  language?: string | null,
): UseOneShotVoiceInputResult {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const watcherRef = useRef<number | null>(null);

  function cleanup(): void {
    if (watcherRef.current !== null) {
      window.clearInterval(watcherRef.current);
      watcherRef.current = null;
    }
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function handleStop(): void {
    setRecording(false);
    cleanup();
    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size === 0) {
      return;
    }
    transcribeAudio(blob, "input.webm", language)
      .then((text) => {
        if (text.trim()) {
          onResult(text.trim());
        }
      })
      .catch((err) => {
        console.error("Failed to transcribe one-shot voice input:", err);
        setError("Не удалось распознать речь.");
      });
  }

  function watchForSilence(stream: MediaStream): void {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    audioContextRef.current = audioContext;

    const data = new Uint8Array(analyser.fftSize);
    let hasSpoken = false;
    let lastVoiceAt = Date.now();
    const startedAt = Date.now();

    watcherRef.current = window.setInterval(() => {
      analyser.getByteTimeDomainData(data);
      const now = Date.now();
      if (rms(data) >= SILENCE_RMS_THRESHOLD) {
        hasSpoken = true;
        lastVoiceAt = now;
      }
      const silentFor = now - lastVoiceAt;
      const elapsed = now - startedAt;
      if ((hasSpoken && silentFor >= SILENCE_DURATION_MS) || elapsed >= MAX_RECORDING_MS) {
        if (recorderRef.current && recorderRef.current.state !== "inactive") {
          recorderRef.current.stop();
        }
      }
    }, WATCHER_INTERVAL_MS);
  }

  function start(): void {
    setError("");
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        streamRef.current = stream;
        chunksRef.current = [];
        const recorder = new MediaRecorder(stream);
        recorderRef.current = recorder;
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            chunksRef.current.push(event.data);
          }
        };
        recorder.onstop = handleStop;
        recorder.start();
        setRecording(true);
        watchForSilence(stream);
      })
      .catch((err) => {
        console.error("Failed to start one-shot voice input:", err);
        setError("Не удалось получить доступ к микрофону.");
        setRecording(false);
        cleanup();
      });
  }

  return { recording, error, start };
}
