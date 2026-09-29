import { useEffect, useSyncExternalStore } from "react";

type Listener = () => void;

export const INACTIVE_CLASS = "page-inactive";
export const DORMANT_CLASS = "page-dormant";

const listeners = new Set<Listener>();
let windowActive = true;
let windowSubscribed = false;

function documentVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

function documentFocused(): boolean {
  return typeof document === "undefined" || document.hasFocus();
}

function notify(): void {
  listeners.forEach((listener) => listener());
}

function subscribeToWindowActivity(): void {
  if (windowSubscribed || typeof window === "undefined") {
    return;
  }
  const subscribe = window.assistantAPI?.onWindowActiveChanged;
  if (!subscribe) {
    return;
  }
  windowSubscribed = true;
  subscribe((active: boolean) => {
    windowActive = active;
    notify();
  });
}

function subscribe(listener: Listener): () => void {
  subscribeToWindowActivity();
  listeners.add(listener);
  if (listeners.size === 1) {
    document.addEventListener("visibilitychange", notify);
    window.addEventListener("focus", notify);
    window.addEventListener("blur", notify);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      document.removeEventListener("visibilitychange", notify);
      window.removeEventListener("focus", notify);
      window.removeEventListener("blur", notify);
    }
  };
}

export function isPageActive(): boolean {
  return windowActive && documentVisible();
}

export function isPageFocused(): boolean {
  return isPageActive() && documentFocused();
}

export function usePageActive(): boolean {
  return useSyncExternalStore(subscribe, isPageActive, () => true);
}

export function usePageFocused(): boolean {
  return useSyncExternalStore(subscribe, isPageFocused, () => true);
}

export function usePageActivityClasses(idle: boolean): void {
  const active = usePageActive();
  const focused = usePageFocused();
  const dormant = !active || (idle && !focused);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle(INACTIVE_CLASS, !active);
    root.classList.toggle(DORMANT_CLASS, dormant);
  }, [active, dormant]);

  useEffect(() => {
    const root = document.documentElement;
    return () => {
      root.classList.remove(INACTIVE_CLASS, DORMANT_CLASS);
    };
  }, []);
}
