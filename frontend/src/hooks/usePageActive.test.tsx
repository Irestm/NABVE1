import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssistantWindowAPI } from "../types";

type ActivityModule = typeof import("./usePageActive");
type PollingModule = typeof import("./usePolling");

let visibility: DocumentVisibilityState = "visible";
let focused = true;
let windowActiveCallback: ((active: boolean) => void) | null = null;

function setVisibility(next: DocumentVisibilityState): void {
  visibility = next;
  document.dispatchEvent(new Event("visibilitychange"));
}

function setFocused(next: boolean): void {
  focused = next;
  window.dispatchEvent(new Event(next ? "focus" : "blur"));
}

function installAssistantApi(): void {
  const api: AssistantWindowAPI = {
    backendBaseUrl: "",
    onWindowActiveChanged: (callback: (active: boolean) => void) => {
      windowActiveCallback = callback;
      return () => {
        windowActiveCallback = null;
      };
    },
  };
  window.assistantAPI = api;
}

async function loadActivity(): Promise<ActivityModule> {
  vi.resetModules();
  return import("./usePageActive");
}

async function loadPolling(): Promise<PollingModule> {
  return import("./usePolling");
}

beforeEach(() => {
  visibility = "visible";
  focused = true;
  windowActiveCallback = null;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  vi.spyOn(document, "hasFocus").mockImplementation(() => focused);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete window.assistantAPI;
  document.documentElement.className = "";
});

describe("usePageActive", () => {
  it("становится неактивной, когда документ скрыт", async () => {
    const { usePageActive } = await loadActivity();
    function Probe(): JSX.Element {
      return <span>{usePageActive() ? "active" : "inactive"}</span>;
    }
    render(<Probe />);
    expect(screen.getByText("active")).toBeTruthy();
    act(() => setVisibility("hidden"));
    expect(screen.getByText("inactive")).toBeTruthy();
    act(() => setVisibility("visible"));
    expect(screen.getByText("active")).toBeTruthy();
  });

  it("слушает сворачивание окна из Electron", async () => {
    installAssistantApi();
    const { usePageActive } = await loadActivity();
    function Probe(): JSX.Element {
      return <span>{usePageActive() ? "active" : "inactive"}</span>;
    }
    render(<Probe />);
    expect(windowActiveCallback).not.toBeNull();
    act(() => windowActiveCallback?.(false));
    expect(screen.getByText("inactive")).toBeTruthy();
    act(() => windowActiveCallback?.(true));
    expect(screen.getByText("active")).toBeTruthy();
  });

  it("ставит классы на корень: неактивна и спящий фон", async () => {
    const { usePageActivityClasses, INACTIVE_CLASS, DORMANT_CLASS } = await loadActivity();
    function Probe({ idle }: { idle: boolean }): null {
      usePageActivityClasses(idle);
      return null;
    }
    const root = document.documentElement;
    const { rerender } = render(<Probe idle />);
    expect(root.classList.contains(INACTIVE_CLASS)).toBe(false);
    expect(root.classList.contains(DORMANT_CLASS)).toBe(false);

    act(() => setFocused(false));
    expect(root.classList.contains(DORMANT_CLASS)).toBe(true);
    expect(root.classList.contains(INACTIVE_CLASS)).toBe(false);

    rerender(<Probe idle={false} />);
    expect(root.classList.contains(DORMANT_CLASS)).toBe(false);

    act(() => setVisibility("hidden"));
    expect(root.classList.contains(INACTIVE_CLASS)).toBe(true);
    expect(root.classList.contains(DORMANT_CLASS)).toBe(true);
  });
});

describe("usePolling", () => {
  it("опрашивает сразу и по интервалу, на скрытой странице — пауза, при возврате — сразу", async () => {
    vi.useFakeTimers();
    await loadActivity();
    const { usePolling } = await loadPolling();
    const callback = vi.fn();
    function Probe(): null {
      usePolling(callback, 1000);
      return null;
    }
    render(<Probe />);
    expect(callback).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(callback).toHaveBeenCalledTimes(4);

    act(() => setVisibility("hidden"));
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(callback).toHaveBeenCalledTimes(4);

    act(() => setVisibility("visible"));
    expect(callback).toHaveBeenCalledTimes(5);
  });

  it("на скрытой странице опрашивает реже, если задан hiddenIntervalMs", async () => {
    vi.useFakeTimers();
    await loadActivity();
    const { usePolling } = await loadPolling();
    const callback = vi.fn();
    function Probe(): null {
      usePolling(callback, 1000, { hiddenIntervalMs: 5000 });
      return null;
    }
    render(<Probe />);
    act(() => setVisibility("hidden"));
    callback.mockClear();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(callback).toHaveBeenCalledTimes(2);
  });
});
