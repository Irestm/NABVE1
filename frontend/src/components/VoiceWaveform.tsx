import { useEffect, useRef } from "react";
import { useMicAnalyser } from "../hooks/useMicAnalyser";
import { useSyntheticAnalyser } from "../hooks/useSyntheticAnalyser";
import "./VoiceWaveform.css";

interface VoiceWaveformProps {
  mode: "listening" | "speaking";
  active: boolean;
}

const BAR_COUNT = 28;

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
  ctx.fill();
}

function readCssColor(varName: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || "#4f8cff";
}

export function VoiceWaveform({ mode, active }: VoiceWaveformProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const micAnalyserRef = useMicAnalyser(mode === "listening" && active);
  const synthAnalyserRef = useSyntheticAnalyser(mode === "speaking" && active);
  const analyserRef = mode === "listening" ? micAnalyserRef : synthAnalyserRef;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) {
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    const color = readCssColor(mode === "listening" ? "--glow-listening" : "--glow-speaking");
    const data = new Uint8Array(32);
    let frameId: number;

    function resize(): void {
      const rect = canvas!.getBoundingClientRect();
      canvas!.width = Math.max(1, rect.width * dpr);
      canvas!.height = Math.max(1, rect.height * dpr);
    }
    resize();
    window.addEventListener("resize", resize);

    function draw(): void {
      const width = canvas!.width;
      const height = canvas!.height;
      ctx!.clearRect(0, 0, width, height);

      const analyser = analyserRef.current;
      if (analyser && active) {
        analyser.getByteFrequencyData(data);
      } else {
        data.fill(0);
      }

      const barWidth = width / BAR_COUNT;
      const gap = barWidth * 0.35;
      for (let i = 0; i < BAR_COUNT; i += 1) {
        const dataIndex = Math.floor((i / BAR_COUNT) * data.length);
        const value = active ? data[dataIndex] / 255 : 0;
        const barHeight = Math.max(height * 0.08, value * height);
        const x = i * barWidth + gap / 2;
        const y = (height - barHeight) / 2;
        ctx!.globalAlpha = active ? 0.35 + value * 0.65 : 0.2;
        ctx!.fillStyle = color;
        roundedRect(ctx!, x, y, barWidth - gap, barHeight, (barWidth - gap) / 2);
      }

      frameId = requestAnimationFrame(draw);
    }
    draw();

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", resize);
    };
  }, [mode, active, analyserRef]);

  return (
    <div className={`voice-waveform voice-waveform--${mode}${active ? " voice-waveform--active" : ""}`}>
      <canvas ref={canvasRef} />
    </div>
  );
}
