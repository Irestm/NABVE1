import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantLayout } from "./AssistantLayout";
import { AssistantToggleButton } from "./AssistantToggleButton";
import type { PanelState, PanelStore } from "./panelState";
import type { AssistantContextProvider } from "./types";

const provider: AssistantContextProvider = {
  module: "english",
  apiBase: "/api/english",
  scope: "library",
  scopeId: 0,
  title: "Тест",
  suggestions: ["Справлюсь ли я с этим сериалом/фильмом?"],
  getContext: () => ({ screen: "library" }),
};

function fakeStore(initial: PanelState): PanelStore & { saved: PanelState[] } {
  const saved: PanelState[] = [];
  return {
    saved,
    load: vi.fn(async () => initial),
    save: vi.fn(async (state: PanelState) => {
      saved.push(state);
    }),
  };
}

function setWindowWidth(width: number): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  window.dispatchEvent(new Event("resize"));
}

function renderLayout(store: PanelStore): ReturnType<typeof render> {
  return render(
    <AssistantLayout provider={provider} store={store}>
      <header>
        <AssistantToggleButton />
      </header>
      <p>content</p>
    </AssistantLayout>,
  );
}

beforeEach(() => {
  setWindowWidth(1400);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AssistantLayout", () => {
  it("renders nothing of the panel while hidden and opens from the header icon", async () => {
    const store = fakeStore({ open: false, width: 500 });
    renderLayout(store);
    await waitFor(() => expect(store.load).toHaveBeenCalled());

    expect(screen.queryByTestId("assistant-dock")).toBeNull();
    expect(screen.queryByTestId("assistant-divider")).toBeNull();

    const toggle = screen.getByRole("button", { name: "Спросить ассистента об этом разделе" });
    expect(toggle.getAttribute("title")).toBe("Спросить ассистента об этом разделе");
    await act(async () => {
      fireEvent.click(toggle);
    });

    expect(screen.getByTestId("assistant-dock").style.width).toBe("500px");
    expect(screen.getByTestId("assistant-divider")).not.toBeNull();
    expect(store.saved.at(-1)).toEqual({ open: true, width: 500 });
    expect(await screen.findByText("Справлюсь ли я с этим сериалом/фильмом?")).not.toBeNull();
  });

  it("restores the saved width and clamps it to 60% of the window", async () => {
    setWindowWidth(1000);
    renderLayout(fakeStore({ open: true, width: 900 }));

    await waitFor(() => expect(screen.getByTestId("assistant-dock").style.width).toBe("600px"));
  });

  it("resets to 380px on double click and saves it", async () => {
    const store = fakeStore({ open: true, width: 520 });
    renderLayout(store);
    const divider = await screen.findByTestId("assistant-divider");

    await act(async () => {
      fireEvent.doubleClick(divider);
    });

    expect(screen.getByTestId("assistant-dock").style.width).toBe("380px");
    expect(store.saved.at(-1)).toEqual({ open: true, width: 380 });
  });

  it("hides via the panel button and stays hidden", async () => {
    const store = fakeStore({ open: true, width: 400 });
    renderLayout(store);
    const hide = await screen.findByRole("button", { name: "Скрыть панель" });

    await act(async () => {
      fireEvent.click(hide);
    });

    expect(screen.queryByTestId("assistant-dock")).toBeNull();
    expect(store.saved.at(-1)).toEqual({ open: false, width: 400 });
  });

  it("overlays the content with a backdrop on narrow windows", async () => {
    setWindowWidth(800);
    const store = fakeStore({ open: true, width: 400 });
    renderLayout(store);
    const backdrop = await screen.findByTestId("assistant-backdrop");

    expect(screen.queryByTestId("assistant-divider")).toBeNull();
    await act(async () => {
      fireEvent.click(backdrop);
    });
    expect(screen.queryByTestId("assistant-dock")).toBeNull();
    expect(store.saved.at(-1)?.open).toBe(false);
  });
});
