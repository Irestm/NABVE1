import { app } from "electron";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
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

let backendProcess: ChildProcess | null = null;

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

  if (backendProcess) {
    return backendProcess;
  }

  const pythonBin = resolvePythonBinary();
  const env = { ...process.env };
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

export function stopBackend(): void {
  if (isExternalBackend()) {
    return;
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}
