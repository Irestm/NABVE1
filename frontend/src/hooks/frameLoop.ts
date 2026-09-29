export const ACTIVE_FRAME_RATE = 30;

const FRAME_TOLERANCE_MS = 2;

export function startFrameLoop(draw: () => void, framesPerSecond: number = ACTIVE_FRAME_RATE): () => void {
  const minFrameIntervalMs = 1000 / framesPerSecond;
  let lastDrawAt = performance.now();
  let frameId = 0;

  function tick(now: number): void {
    if (now - lastDrawAt >= minFrameIntervalMs - FRAME_TOLERANCE_MS) {
      lastDrawAt = now;
      draw();
    }
    frameId = requestAnimationFrame(tick);
  }

  draw();
  frameId = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frameId);
}
