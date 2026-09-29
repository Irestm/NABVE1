import { useEffect, useRef } from "react";
import { usePageActive } from "./usePageActive";

export interface PollingOptions {
  enabled?: boolean;
  hiddenIntervalMs?: number | null;
}

export function usePolling(
  callback: () => unknown,
  intervalMs: number,
  { enabled = true, hiddenIntervalMs = null }: PollingOptions = {},
): void {
  const callbackRef = useRef<() => unknown>(callback);
  const pageActive = usePageActive();

  useEffect(() => {
    callbackRef.current = callback;
  });

  useEffect(() => {
    if (!enabled) {
      return;
    }
    if (pageActive) {
      callbackRef.current();
    }
    const delay: number | null = pageActive ? intervalMs : hiddenIntervalMs;
    if (delay === null) {
      return;
    }
    const id = window.setInterval(() => callbackRef.current(), delay);
    return () => window.clearInterval(id);
  }, [enabled, pageActive, intervalMs, hiddenIntervalMs]);
}
