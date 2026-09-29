import { powerMonitor } from "electron";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { BACKEND_BASE_URL } from "./config";

const POWER_SOURCE_REQUEST_TIMEOUT_MS = 3000;
const LINUX_POWER_POLL_INTERVAL_MS = 15000;
const LINUX_POWER_SUPPLY_DIR = "/sys/class/power_supply";
const LINUX_EXTERNAL_SUPPLY_TYPES: ReadonlySet<string> = new Set(["Mains", "USB"]);

function readSupplyAttribute(supplyDir: string, attribute: string): string | null {
  try {
    return readFileSync(path.join(supplyDir, attribute), "utf-8").trim();
  } catch {
    return null;
  }
}

function isOnBatteryLinux(): boolean {
  let entries: string[];
  try {
    entries = readdirSync(LINUX_POWER_SUPPLY_DIR);
  } catch {
    return false;
  }
  let hasBattery = false;
  for (const entry of entries) {
    const supplyDir = path.join(LINUX_POWER_SUPPLY_DIR, entry);
    const type = readSupplyAttribute(supplyDir, "type");
    if (type === "Battery" && readSupplyAttribute(supplyDir, "scope") !== "Device") {
      hasBattery = true;
    } else if (type !== null && LINUX_EXTERNAL_SUPPLY_TYPES.has(type) && readSupplyAttribute(supplyDir, "online") === "1") {
      return false;
    }
  }
  return hasBattery;
}

export function isOnBatteryPower(): boolean {
  if (process.platform === "linux") {
    return isOnBatteryLinux();
  }
  return powerMonitor.isOnBatteryPower();
}

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
  let lastReported = isOnBatteryPower();
  void reportPowerSource(apiToken, lastReported);

  const report = (onBattery: boolean): void => {
    lastReported = onBattery;
    void reportPowerSource(apiToken, onBattery);
  };

  if (process.platform === "linux") {
    const timer = setInterval(() => {
      const onBattery = isOnBatteryLinux();
      if (onBattery !== lastReported) {
        report(onBattery);
      }
    }, LINUX_POWER_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }

  const handleBattery = (): void => report(true);
  const handleAc = (): void => report(false);
  powerMonitor.on("on-battery", handleBattery);
  powerMonitor.on("on-ac", handleAc);
  return () => {
    powerMonitor.off("on-battery", handleBattery);
    powerMonitor.off("on-ac", handleAc);
  };
}
