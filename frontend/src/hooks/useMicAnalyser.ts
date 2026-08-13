import { useEffect, useRef, type MutableRefObject } from "react";

/**
 * Wires the system microphone to a real Web Audio AnalyserNode while `active`
 * is true, for driving the "listening" waveform off the user's actual input
 * level. Returns a ref (not state) so a requestAnimationFrame draw loop can
 * read the current analyser without re-subscribing every frame.
 */
export function useMicAnalyser(active: boolean): MutableRefObject<AnalyserNode | null> {
  const analyserRef = useRef<AnalyserNode | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!active) {
      return;
    }

    let cancelled = false;

    async function setup(): Promise<void> {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 64;
        analyser.smoothingTimeConstant = 0.7;
        source.connect(analyser);

        streamRef.current = stream;
        contextRef.current = context;
        analyserRef.current = analyser;
      } catch (error) {
        console.error("Failed to set up the microphone analyser:", error);
        analyserRef.current = null;
      }
    }

    void setup();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void contextRef.current?.close();
      streamRef.current = null;
      contextRef.current = null;
      analyserRef.current = null;
    };
  }, [active]);

  return analyserRef;
}
