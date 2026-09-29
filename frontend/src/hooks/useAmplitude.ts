import { useEffect, type RefObject } from "react";
import type { AssistantState } from "../types";
import { startFrameLoop } from "./frameLoop";
import { useMicAnalyser } from "./useMicAnalyser";
import { usePageActive } from "./usePageActive";
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
  // Fallback only — onboarding normally drives the real mic analyser (see
  // `listening` below), this just covers the moment before getUserMedia
  // resolves, or if it's denied/fails.
  onboarding: 0.18,
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
  // Onboarding (see modules/user_profile/onboarding.py) records the user's
  // spoken answers the exact same way a normal voice command does — the
  // orb reacting to actual mic input during the first-run interview, not
  // just sitting on a flat baseline, was the whole point of adding this.
  const pageActive = usePageActive();
  const listening = pageActive && (state === "listening" || state === "onboarding");
  const synthActive = pageActive && (state === "speaking" || state === "thinking" || state === "processing");

  const micAnalyserRef = useMicAnalyser(listening);
  const synthAnalyserRef = useSyntheticAnalyser(synthActive);

  useEffect(() => {
    const baseline = IDLE_BASELINE[state] ?? 0.14;
    const setAmplitude = (value: number): void => {
      targetRef.current?.style.setProperty("--amplitude", value.toFixed(3));
    };

    if (!listening && !synthActive) {
      setAmplitude(baseline);
      return;
    }

    const data = new Uint8Array(32);
    return startFrameLoop(() => {
      const analyser = listening ? micAnalyserRef.current : synthAnalyserRef.current;
      let amplitude = baseline;
      if (analyser) {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) {
          sum += data[i];
        }
        amplitude = sum / data.length / 255;
      }
      setAmplitude(amplitude);
    });
  },[listening, synthActive, state, targetRef, micAnalyserRef, synthAnalyserRef]);
}
