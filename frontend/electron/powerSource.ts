import { powerMonitor } from "electron";
import { BACKEND_BASE_URL } from "./config";

const POWER_SOURCE_REQUEST_TIMEOUT_MS = 3000;

async function reportPowerSource(apiToken: string, onBattery: boolean): Promise<void> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/api/power/source`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Assistant-Token": apiToken },
      body: JSON.stringify({ on_battery: onBattery }),
      signal: AbortSignal.timeout(POWER_SOURCE_REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      process.stderr.write(`[power] PUT /api/power/source failed with status ${response.status}\n`);
    }
  } catch (error: unknown) {
    process.stderr.write(`[power] PUT /api/power/source failed: ${String(error)}\n`);
  }
}

export function startPowerSourceSync(apiToken: string): () => void {
  const handleBattery = (): void => {
    void reportPowerSource(apiToken, true);
  };
  const handleAc = (): void => {
    void reportPowerSource(apiToken, false);
  };
  powerMonitor.on("on-battery", handleBattery);
  powerMonitor.on("on-ac", handleAc);
  void reportPowerSource(apiToken, powerMonitor.isOnBatteryPower());
  return () => {
    powerMonitor.off("on-battery", handleBattery);
    powerMonitor.off("on-ac", handleAc);
  };
}
