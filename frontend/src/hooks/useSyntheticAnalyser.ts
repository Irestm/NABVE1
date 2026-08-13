import { useEffect, useRef, type MutableRefObject } from "react";

/**
 * Drives the "speaking" waveform through a real (but inaudible) Web Audio
 * AnalyserNode graph. The Python backend currently plays synthesized TTS
 * audio directly on the host machine rather than streaming PCM to the
 * renderer, so there is no real waveform to tap yet; this generates a
 * speech-shaped energy signal through an actual AnalyserNode so the
 * component reads real Web Audio frequency data end to end, and can be
 * pointed at a real TTS MediaStream later with no changes on the drawing side.
 */
export function useSyntheticAnalyser(active: boolean): MutableRefObject<AnalyserNode | null> {
  const analyserRef = useRef<AnalyserNode | null>(null);

  useEffect(() => {
    if (!active) {
      return;
    }

    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 64;
    analyser.smoothingTimeConstant = 0.6;

    const oscillatorLow = context.createOscillator();
    oscillatorLow.type = "sawtooth";
    oscillatorLow.frequency.value = 120;
    const oscillatorHigh = context.createOscillator();
    oscillatorHigh.type = "square";
    oscillatorHigh.frequency.value = 340;

    const envelope = context.createGain();
    envelope.gain.value = 0;
    const silentOutput = context.createGain();
    silentOutput.gain.value = 0;

    oscillatorLow.connect(envelope);
    oscillatorHigh.connect(envelope);
    envelope.connect(analyser);
    analyser.connect(silentOutput);
    silentOutput.connect(context.destination);

    oscillatorLow.start();
    oscillatorHigh.start();

    let cancelled = false;
    let timeoutId: number;

    function modulate(): void {
      if (cancelled) {
        return;
      }
      const level = 0.12 + Math.random() * 0.4;
      envelope.gain.setTargetAtTime(level, context.currentTime, 0.05);
      timeoutId = window.setTimeout(modulate, 80 + Math.random() * 90);
    }
    modulate();

    analyserRef.current = analyser;

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      oscillatorLow.stop();
      oscillatorHigh.stop();
      void context.close();
      analyserRef.current = null;
    };
  }, [active]);

  return analyserRef;
}
