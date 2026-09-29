import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { PowerStatus } from "../api/power";
import type { AssistantWindowAPI } from "../types";
import { PowerSettingsPanel } from "./PowerSettingsPanel";

const BASE_STATUS: PowerStatus = {
  on_battery: true,
  mode: "auto",
  saving_active: true,
  idle_timeout_battery_s: 60,
  idle_timeout_ac_s: 900,
  gpu_on_battery: false,
  worker_running: true,
  worker_device: "cpu",
};

interface RecordedRequest {
  url: string;
  method: string;
  body: unknown;
}

let requests: RecordedRequest[] = [];
let current: PowerStatus = BASE_STATUS;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  requests = [];
  current = { ...BASE_STATUS };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
      requests.push({ url: String(input), method, body });
      if (method === "PUT") {
        current = { ...current, ...(body as Partial<PowerStatus>) };
      }
      return jsonResponse(current);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.assistantAPI;
});

function putRequests(): RecordedRequest[] {
  return requests.filter((request) => request.method === "PUT");
}

describe("PowerSettingsPanel", () => {
  it("показывает состояние питания и воркера", async () => {
    render(<PowerSettingsPanel />);
    expect(await screen.findByText("от батареи")).toBeTruthy();
    expect(screen.getByText("активно")).toBeTruthy();
    expect(screen.getByText("запущен (процессор)")).toBeTruthy();
    expect(requests[0].url).toBe("/api/power");
  });

  it("меняет режим энергосбережения", async () => {
    render(<PowerSettingsPanel />);
    fireEvent.click(await screen.findByRole("radio", { name: "Всегда" }));
    await waitFor(() => expect(putRequests()).toHaveLength(1));
    expect(putRequests()[0]).toEqual({ url: "/api/power/settings", method: "PUT", body: { mode: "always" } });
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Всегда" }).getAttribute("aria-checked")).toBe("true"),
    );
  });

  it("проверяет таймауты и сохраняет их вместе", async () => {
    render(<PowerSettingsPanel />);
    const batteryInput = await screen.findByLabelText("При экономии");
    const saveButton = screen.getByRole("button", { name: "Сохранить" }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);

    fireEvent.change(batteryInput, { target: { value: "5" } });
    expect(screen.getByText(/Допустимо от 10/)).toBeTruthy();
    expect(saveButton.disabled).toBe(true);

    fireEvent.change(batteryInput, { target: { value: "120" } });
    expect(saveButton.disabled).toBe(false);
    fireEvent.click(saveButton);
    await waitFor(() => expect(putRequests()).toHaveLength(1));
    expect(putRequests()[0].body).toEqual({ idle_timeout_battery_s: 120, idle_timeout_ac_s: 900 });
  });

  it("переключает видеокарту на батарее", async () => {
    render(<PowerSettingsPanel />);
    fireEvent.click(await screen.findByLabelText("Использовать видеокарту на батарее"));
    await waitFor(() => expect(putRequests()).toHaveLength(1));
    expect(putRequests()[0].body).toEqual({ gpu_on_battery: true });
  });

  it("скрывает автозапуск вне Electron", async () => {
    render(<PowerSettingsPanel />);
    await screen.findByText("от батареи");
    expect(screen.queryByLabelText("Запускать при входе в систему")).toBeNull();
  });

  it("включает автозапуск через assistantAPI", async () => {
    const setAutostart: Mock<(enabled: boolean) => Promise<boolean>> = vi.fn(async (enabled: boolean) => enabled);
    const api: AssistantWindowAPI = {
      backendBaseUrl: "",
      getAutostart: vi.fn(async () => false),
      setAutostart,
    };
    window.assistantAPI = api;
    render(<PowerSettingsPanel />);
    const checkbox = (await screen.findByLabelText("Запускать при входе в систему")) as HTMLInputElement;
    await waitFor(() => expect(checkbox.disabled).toBe(false));
    expect(checkbox.checked).toBe(false);
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox.checked).toBe(true));
    expect(setAutostart).toHaveBeenCalledWith(true);
  });
});
