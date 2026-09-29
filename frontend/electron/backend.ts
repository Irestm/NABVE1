import { app } from "electron";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
import { BACKEND_BASE_URL } from "./config";
import { isOnBatteryPower } from "./powerSource";
import { backendResourcesDir, packagedDataDir, packagedLogsDir, readStockfishPath, venvPythonBin } from "./setup";

// Dev: run straight from the repo checkout with whatever `python3`/`python`
// is on PATH (matches the README's manual-setup instructions). Packaged:
// run the copy of the backend source electron-builder placed under
// resourcesPath (see electron-builder.yml's extraResources) through the
// venv electron/setup.ts created on first launch — never the bare
// PATH-resolved interpreter, since a packaged install can't assume the
// end user has Python (or any of this app's pip dependencies) installed
// system-wide at all.
const DEV_PROJECT_ROOT = path.resolve(__dirname, "..", "..");

const SHUTDOWN_REQUEST_TIMEOUT_MS = 1000;
const GRACEFUL_EXIT_TIMEOUT_MS = 3000;
const FORCED_EXIT_TIMEOUT_MS = 2000;
const GROUP_EXIT_POLL_INTERVAL_MS = 100;

let backendProcess: ChildProcess | null = null;
let shuttingDown = false;
let stopPromise: Promise<void> | null = null;

function resolvePythonBinary(): string {
  if (process.env.ASSISTANT_PYTHON_BIN) {
    return process.env.ASSISTANT_PYTHON_BIN;
  }
  if (app.isPackaged) {
    return venvPythonBin();
  }
  return process.platform === "win32" ? "python" : "python3";
}

// Set by the "dev:docker" npm script when the backend is already running as
// the "backend" service in docker-compose.yml — Electron should just talk to
// it over HTTP instead of spawning its own Python process.
function isExternalBackend(): boolean {
  return process.env.ASSISTANT_EXTERNAL_BACKEND === "1";
}

export async function startBackend(): Promise<ChildProcess | null> {
  if (isExternalBackend()) {
    process.stdout.write("[backend] ASSISTANT_EXTERNAL_BACKEND=1, assuming docker compose backend is running\n");
    return null;
  }

  if (shuttingDown) {
    return null;
  }

  if (backendProcess) {
    return backendProcess;
  }

  const pythonBin = resolvePythonBinary();
  const env = { ...process.env };
  env.ASSISTANT_ON_BATTERY = isOnBatteryPower() ? "1" : "0";
  if (app.isPackaged) {
    // See core/config.py's ASSISTANT_DATA_DIR/ASSISTANT_LOGS_DIR override —
    // the packaged backend source tree may be read-only (AppImage mount),
    // so data/logs must live in a writable per-user directory instead of
    // next to the source, same as the venv itself (electron/setup.ts).
    env.ASSISTANT_DATA_DIR = packagedDataDir();
    env.ASSISTANT_LOGS_DIR = packagedLogsDir();
    const stockfishPath = await readStockfishPath();
    if (stockfishPath) {
      env.ASSISTANT_STOCKFISH_PATH = stockfishPath;
    }
  }

  const child = spawn(pythonBin, ["-m", "core.watchdog"], {
    cwd: app.isPackaged ? backendResourcesDir() : DEV_PROJECT_ROOT,
    stdio: "pipe",
    detached: process.platform !== "win32",
    windowsHide: true,
    env,
  });

  child.stdout?.on("data", (chunk: Buffer) => {
    process.stdout.write(`[backend] ${chunk.toString()}`);
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    process.stderr.write(`[backend] ${chunk.toString()}`);
  });
  child.on("exit", (code: number | null) => {
    process.stdout.write(`[backend] exited with code ${code}\n`);
    backendProcess = null;
  });
  // Without a listener, a spawn failure (missing/corrupt venv interpreter,
  // EACCES, ...) fires Node's EventEmitter "error" event with nothing
  // attached, which throws and crashes the whole Electron main process —
  // see electron/setup.ts's runCommand for the same handler shape used
  // there.
  child.on("error", (error: Error) => {
    process.stderr.write(`[backend] failed to start: ${String(error)}\n`);
    backendProcess = null;
  });

  backendProcess = child;
  return child;
}

function hasExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (hasExited(child)) {
    return Promise.resolve(true);
  }
  return new Promise<boolean>((resolve) => {
    const onExit = (): void => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      child.off("exit", onExit);
      resolve(hasExited(child));
    }, timeoutMs);
    child.once("exit", onExit);
  });
}

async function requestGracefulShutdown(): Promise<void> {
  try {
    await fetch(`${BACKEND_BASE_URL}/api/system/shutdown`, {
      method: "POST",
      headers: { "X-Assistant-Token": process.env.ASSISTANT_API_TOKEN ?? "" },
      signal: AbortSignal.timeout(SHUTDOWN_REQUEST_TIMEOUT_MS),
    });
  } catch (error: unknown) {
    process.stderr.write(`[backend] shutdown request failed: ${String(error)}\n`);
  }
}

function signalProcessGroup(child: ChildProcess, signal: NodeJS.Signals | 0): boolean {
  const pid = child.pid;
  if (pid === undefined) {
    return false;
  }
  try {
    process.kill(-pid, signal);
    return true;
  } catch (error: unknown) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ESRCH") {
      return false;
    }
    process.stderr.write(`[backend] failed to send ${signal} to group ${pid}: ${String(error)}\n`);
    if (signal !== 0 && !hasExited(child)) {
      child.kill(signal);
    }
    return !hasExited(child);
  }
}

async function waitForGroupExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  if (!(await waitForExit(child, timeoutMs))) {
    return false;
  }
  while (signalProcessGroup(child, 0)) {
    if (Date.now() >= deadline) {
      return false;
    }
    await new Promise<void>((resolve) => setTimeout(resolve, GROUP_EXIT_POLL_INTERVAL_MS));
  }
  return true;
}

function killWindowsProcessTree(child: ChildProcess): Promise<void> {
  const pid = child.pid;
  if (pid === undefined || hasExited(child)) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    killer.on("error", (error: Error) => {
      process.stderr.write(`[backend] taskkill failed: ${String(error)}\n`);
      resolve();
    });
    killer.on("exit", () => resolve());
  });
}

async function terminateBackend(child: ChildProcess): Promise<void> {
  await requestGracefulShutdown();
  if (process.platform === "win32") {
    if (!(await waitForExit(child, GRACEFUL_EXIT_TIMEOUT_MS))) {
      await killWindowsProcessTree(child);
      await waitForExit(child, FORCED_EXIT_TIMEOUT_MS);
    }
    return;
  }
  signalProcessGroup(child, "SIGTERM");
  if (await waitForGroupExit(child, GRACEFUL_EXIT_TIMEOUT_MS)) {
    return;
  }
  process.stderr.write("[backend] did not exit after SIGTERM, sending SIGKILL\n");
  signalProcessGroup(child, "SIGKILL");
  await waitForGroupExit(child, FORCED_EXIT_TIMEOUT_MS);
}

export function stopBackend(): Promise<void> {
  shuttingDown = true;
  if (stopPromise) {
    return stopPromise;
  }
  const child = backendProcess;
  if (isExternalBackend() || !child) {
    stopPromise = Promise.resolve();
    return stopPromise;
  }
  stopPromise = terminateBackend(child).finally(() => {
    backendProcess = null;
  });
  return stopPromise;
}
