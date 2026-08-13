import { useEffect, type RefObject } from "react";
import type { AssistantState } from "../types";
import { useMicAnalyser } from "./useMicAnalyser";
import { useSyntheticAnalyser } from "./useSyntheticAnalyser";

// Idle/error/paused have no real or synthetic audio source, but the avatar
// designs (the sun's corona, the cloud's puff) still want *some* --amplitude
// value to breathe on instead of sitting perfectly flat. These are the
// per-state baseline levels used when neither analyser is active.
const IDLE_BASELINE: Partial<Record<AssistantState, number>> = {
  idle: 0.14,
  processing: 0.3,
  thinking: 0.34,
  error: 0.4,
  paused: 0.08,
};

/**
 * Drives a `--amplitude` CSS custom property (0..1) on `targetRef`'s element
 * every animation frame, sourced from the real microphone while `state` is
 * "listening" and from the existing inaudible synthetic analyser while
 * "speaking"/"thinking"/"processing" (see useMicAnalyser/useSyntheticAnalyser
 * — both already used by VoiceWaveform, reused here rather than plumbing a
 * second copy of mic/TTS-level state through React). Written directly to the
 * DOM instead of React state so avatar designs can react to loudness at
 * animation-frame rate without re-rendering React on every sample.
 */
export function useAmplitude(targetRef: RefObject<HTMLElement>, state: AssistantState): void {
  const listening = state === "listening";
  const synthActive = state === "speaking" || state === "thinking" || state === "processing";

  const micAnalyserRef = useMicAnalyser(listening);
  const synthAnalyserRef = useSyntheticAnalyser(synthActive);

  useEffect(() => {
    let frameId: number;
    const data = new Uint8Array(32);
    const baseline = IDLE_BASELINE[state] ?? 0.14;

    function loop(): void {
      const analyser = listening ? micAnalyserRef.current : synthActive ? synthAnalyserRef.current : null;
      let amplitude = baseline;
      if (analyser) {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) {
          sum += data[i];
        }
        amplitude = sum / data.length / 255;
      }
      targetRef.current?.style.setProperty("--amplitude", amplitude.toFixed(3));
      frameId = requestAnimationFrame(loop);
    }
    loop();

    return () => cancelAnimationFrame(frameId);
  }, [listening, synthActive, state, targetRef, micAnalyserRef, synthAnalyserRef]);
}
