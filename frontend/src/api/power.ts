import { requestJson } from "./client";

export type PowerMode = "auto" | "always" | "off";
export type WorkerDevice = "cuda" | "cpu";

export interface PowerStatus {
  on_battery: boolean;
  mode: PowerMode;
  saving_active: boolean;
  idle_timeout_battery_s: number;
  idle_timeout_ac_s: number;
  gpu_on_battery: boolean;
  worker_running: boolean;
  worker_device: WorkerDevice | null;
}

export interface PowerSettingsUpdate {
  mode?: PowerMode;
  idle_timeout_battery_s?: number;
  idle_timeout_ac_s?: number;
  gpu_on_battery?: boolean;
}

export const IDLE_TIMEOUT_MIN_S = 10;
export const IDLE_TIMEOUT_MAX_S = 86400;

export function getPowerStatus(): Promise<PowerStatus> {
  return requestJson<PowerStatus>("/api/power");
}

export function updatePowerSettings(update: PowerSettingsUpdate): Promise<PowerStatus> {
  return requestJson<PowerStatus>("/api/power/settings", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}
