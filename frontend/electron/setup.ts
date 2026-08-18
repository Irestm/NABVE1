import { app } from "electron";
import { spawn, SpawnOptionsWithoutStdio } from "node:child_process";
import { createWriteStream } from "node:fs";
import fs from "node:fs/promises";
import https from "node:https";
import path from "node:path";

// Bump this whenever requirements.txt or the system-package lists below
// gain a new entry — an existing install's persisted setup_state.json will
// then be considered stale and runSetup() runs again, instead of the app
// silently starting with dependencies missing forever.
const SETUP_SCHEMA_VERSION = 1;

const PYTHON_MIN_MAJOR = 3;
const PYTHON_MIN_MINOR = 12;

// See core/voice/silero_tts.py's own module docstring — this weights file
// isn't on pip, and is the one binary asset the app needs beyond
// pip/system packages.
const SILERO_WEIGHTS_URL = "https://huggingface.co/imperialwool/silero-model-v3-ru/resolve/main/model.pt";

// Source of truth is requirements.txt's own per-module system-package
// comments (and Dockerfile, which installs the same list for the
// containerized dev path) — keep this list in sync by hand when either of
// those changes; there's no manifest-extraction tooling in this project,
// and building one just for this installer would be overkill.
const LINUX_APT_PACKAGES = [
  "python3-venv",
  "python3-pip",
  "python3-tk",
  "python3-dev",
  "wmctrl",
  "xdotool",
  "libnotify-bin",
  "libreoffice",
  "ffmpeg",
  "tesseract-ocr",
  "tesseract-ocr-rus",
  "stockfish",
];

// wmctrl/xdotool/libnotify-bin have no Windows equivalent needed — Windows
// uses pygetwindow (pip) and native toast notifications instead (see
// core/os_adapter/windows.py) — so this list is shorter than the apt one.
// IDs verified against the public winget-pkgs manifests.
const WINGET_PACKAGES = [
  "TheDocumentFoundation.LibreOffice",
  "Gyan.FFmpeg",
  "UB-Mannheim.TesseractOCR",
  "Stockfish.Stockfish",
];

// Python is installed straight from python.org (see installWindowsPython
// below), not through winget — see that function's own comment for why.
// Pinned to the newest 3.12.x release that actually ships a Windows
// installer: python.org occasionally cuts a source-only patch with no
// accompanying Windows/macOS binaries (3.12.11 through 3.12.14 are exactly
// that, per python.org/downloads/windows/ — confirmed by hand against that
// page, not assumed). Bump by hand only once a newer 3.12.x is confirmed to
// have a python-*-amd64.exe listed there.
const PYTHON_INSTALLER_VERSION = "3.12.10";
const PYTHON_INSTALLER_URL = `https://www.python.org/ftp/python/${PYTHON_INSTALLER_VERSION}/python-${PYTHON_INSTALLER_VERSION}-amd64.exe`;

export interface SetupProgress {
  step: string;
  percent: number;
}

interface SetupState {
  schemaVersion: number;
  // Windows only: winget's Stockfish package isn't guaranteed to land on
  // PATH (see this module's findWindowsStockfishAfterInstall) — when we had
  // to locate it manually, the resolved path is persisted here so
  // backend.ts can pass it to the Python process as ASSISTANT_STOCKFISH_PATH
  // on every subsequent launch, not just the one that just installed it.
  stockfishPath: string | null;
}

function userDataDir(): string {
  return app.getPath("userData");
}

export function venvDir(): string {
  return path.join(userDataDir(), "venv");
}

export function venvPythonBin(): string {
  return process.platform === "win32"
    ? path.join(venvDir(), "Scripts", "python.exe")
    : path.join(venvDir(), "bin", "python3");
}

export function packagedDataDir(): string {
  return path.join(userDataDir(), "data");
}

export function packagedLogsDir(): string {
  return path.join(userDataDir(), "logs");
}

export function backendResourcesDir(): string {
  return path.join(process.resourcesPath, "backend");
}

function setupStatePath(): string {
  return path.join(userDataDir(), "setup_state.json");
}

function setupLogPath(): string {
  return path.join(packagedLogsDir(), "setup.log");
}

async function readSetupState(): Promise<SetupState | null> {
  try {
    const raw = await fs.readFile(setupStatePath(), "utf-8");
    return JSON.parse(raw) as SetupState;
  } catch {
    return null;
  }
}

async function writeSetupState(state: SetupState): Promise<void> {
  await fs.writeFile(setupStatePath(), JSON.stringify(state, null, 2), "utf-8");
}

export async function needsSetup(): Promise<boolean> {
  const state = await readSetupState();
  return state === null || state.schemaVersion !== SETUP_SCHEMA_VERSION;
}

export async function readStockfishPath(): Promise<string | null> {
  const state = await readSetupState();
  return state?.stockfishPath ?? null;
}

async function appendSetupLog(text: string): Promise<void> {
  await fs.mkdir(packagedLogsDir(), { recursive: true });
  await fs.appendFile(setupLogPath(), text.endsWith("\n") ? text : `${text}\n`, "utf-8");
}

interface CommandResult {
  stdout: string;
  stderr: string;
}

// Carries the child process's exit code alongside the message, so callers
// that need to react to a *specific* failure (see installWindowsPackage's
// winget-source-reset retry below) don't have to regex-parse it back out of
// the formatted error text.
class CommandError extends Error {
  constructor(
    message: string,
    public readonly exitCode: number | null,
  ) {
    super(message);
  }
}

// Every process this module spawns goes through here: stdio is always
// piped (never inherited into a console), and windowsHide guarantees no
// terminal window flashes on Windows for any of these steps — the whole
// point of this module is that the user never sees a console at all.
function runCommand(
  label: string,
  command: string,
  args: string[],
  options: SpawnOptionsWithoutStdio = {},
): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      windowsHide: true,
      ...options,
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      void appendSetupLog(`[${label}] failed to start: ${String(error)}`);
      reject(error);
    });
    child.on("exit", (code) => {
      void appendSetupLog(`[${label}] $ ${command} ${args.join(" ")}\n(exit ${code})\n${stdout}\n${stderr}`);
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(
          new CommandError(
            `${label}: "${command} ${args.join(" ")}" exited with code ${code}\n${stderr.slice(-2000)}`,
            code,
          ),
        );
      }
    });
  });
}

function parsePythonVersion(versionOutput: string): [number, number] | null {
  const match = /Python (\d+)\.(\d+)\.\d+/.exec(versionOutput);
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2])];
}

async function findSystemPython(): Promise<string | null> {
  const candidates = process.platform === "win32" ? ["python", "python3"] : ["python3"];
  for (const candidate of candidates) {
    try {
      const { stdout, stderr } = await runCommand(`python-version-check:${candidate}`, candidate, ["--version"]);
      const parsed = parsePythonVersion(stdout || stderr);
      if (parsed && (parsed[0] > PYTHON_MIN_MAJOR || (parsed[0] === PYTHON_MIN_MAJOR && parsed[1] >= PYTHON_MIN_MINOR))) {
        return candidate;
      }
    } catch {
      // Not found or not runnable — try the next candidate / fall through
      // to installing it.
    }
  }
  return null;
}

// A process that just installed Python via winget doesn't see the updated
// PATH until it restarts (Windows only refreshes PATH for *new* processes
// launched after the registry change, and this Electron process is already
// running) — so `spawn("python", ...)` right after the winget install can
// still fail even though installation genuinely succeeded. Locate the
// python.org-style per-user install winget's Python package wraps, instead
// of assuming PATH already reflects it.
async function findWindowsPythonAfterInstall(): Promise<string | null> {
  const base = path.join(process.env.LOCALAPPDATA ?? "", "Programs", "Python");
  try {
    const entries = await fs.readdir(base);
    const match = entries.find((name) => /^Python3\d\d$/.test(name));
    if (!match) {
      return null;
    }
    const candidate = path.join(base, match, "python.exe");
    await fs.access(candidate);
    return candidate;
  } catch {
    return null;
  }
}

async function findFileRecursive(dir: string, pattern: RegExp, maxDepth: number): Promise<string | null> {
  if (maxDepth < 0) {
    return null;
  }
  let entries: import("node:fs").Dirent[];
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return null;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isFile() && pattern.test(entry.name)) {
      return full;
    }
    if (entry.isDirectory()) {
      const found = await findFileRecursive(full, pattern, maxDepth - 1);
      if (found) {
        return found;
      }
    }
  }
  return null;
}

// Same PATH-refresh caveat as Python above: winget's Stockfish package
// isn't guaranteed to be on PATH in this already-running process, so a
// direct `spawn("stockfish", ...)` from chess_adapter.py could fail even
// after a successful install. Fall back to scanning winget's own per-user
// package cache for the executable.
async function findWindowsStockfishAfterInstall(): Promise<string | null> {
  const base = path.join(process.env.LOCALAPPDATA ?? "", "Microsoft", "WinGet", "Packages");
  const entries = await fs.readdir(base).catch(() => [] as string[]);
  const packageDir = entries.find((name) => name.startsWith("Stockfish.Stockfish_"));
  if (!packageDir) {
    return null;
  }
  return findFileRecursive(path.join(base, packageDir), /^stockfish.*\.exe$/i, 3);
}

async function installLinuxSystemPackages(): Promise<void> {
  // A single pkexec prompt covers the whole list — apt-get install is
  // idempotent, so already-present packages (including python3 itself on
  // most systems) are just skipped quickly rather than needing a separate
  // "is it missing" check first.
  await runCommand("apt-get install", "pkexec", ["apt-get", "install", "-y", ...LINUX_APT_PACKAGES], {
    env: { ...process.env, DEBIAN_FRONTEND: "noninteractive" },
  });
}

// `winget install` with no `--source` refreshes and searches EVERY
// configured source, including the built-in `msstore` one — and `msstore`
// has its own separate one-time agreement (Microsoft Store Terms of
// Transaction + sending the machine's 2-letter region) that has nothing to
// do with the winget-pkgs community source WINGET_PACKAGES actually comes
// from. On a machine where that msstore agreement was never accepted, the
// source refresh fails outright with 0x8a15000f ("Data required by the
// source is missing") and drags every install down with it, no matter how
// many times the user clicks "Повторить" — confirmed against a real user's
// setup.log, which showed the msstore agreement text on the very first
// attempt. Scoping to `--source winget` sidesteps msstore entirely, since
// we never need it.
const WINGET_SOURCE = "winget";

// Kept as a second-layer fallback, not the primary fix above: even scoped
// to a single source, winget's own local index for it can independently go
// stale/uninitialized (microsoft/winget-cli#4799, #5253) and fail with this
// same code. `winget source reset --force` rebuilds it — BUT that command
// itself requires admin privileges (confirmed against the same real user's
// setup.log: it failed with "This command requires administrator
// privileges to execute" right after the scoped install above also failed
// with 0x8a15000f), which this per-user, no-elevation installer never has.
// So on a machine whose winget-source index is this broken, the reset
// attempt below is expected to fail too and re-raise the original error —
// it's a no-op safety net for the *other*, non-admin-requiring causes of
// this same code, not a guaranteed fix for every cause of it. This is also
// exactly why installWindowsPackages() below is non-fatal: a machine in
// this state must still be able to finish setup and run the assistant, just
// without LibreOffice/FFmpeg/Tesseract/Stockfish until winget itself is
// fixed (see WINGET_SOURCE_DATA_MISSING_CODE's own troubleshooting: run
// `winget source reset --force` from an elevated terminal by hand).
const WINGET_SOURCE_DATA_MISSING_CODE = 2316632079; // 0x8a15000f

// Optional, non-Python system packages only — see installWindowsPython for
// why Python itself was pulled out of this winget-based path entirely.
// Deliberately non-fatal (unlike installWindowsPython, unlike
// installLinuxSystemPackages): none of LibreOffice/FFmpeg/Tesseract/
// Stockfish are required for the assistant to start and run — each is only
// needed by one specific feature (file conversion / audio / OCR / chess),
// which will itself report "not available" if missing — so a broken winget
// (see WINGET_SOURCE_DATA_MISSING_CODE above) shouldn't block first run
// entirely the way it used to when Python installation depended on the
// same winget call succeeding.
async function installWindowsPackages(): Promise<void> {
  for (const id of WINGET_PACKAGES) {
    try {
      await installWindowsPackage(id);
    } catch (error) {
      void appendSetupLog(`[winget install ${id}] non-fatal, continuing without it: ${String(error)}`);
    }
  }
}

async function installWindowsPackage(id: string, retriedAfterSourceReset = false): Promise<void> {
  try {
    await runCommand(`winget install ${id}`, "winget", [
      "install",
      "--id",
      id,
      "-e",
      "--source",
      WINGET_SOURCE,
      "--silent",
      "--accept-package-agreements",
      "--accept-source-agreements",
    ]);
  } catch (error) {
    if (
      retriedAfterSourceReset ||
      !(error instanceof CommandError) ||
      error.exitCode !== WINGET_SOURCE_DATA_MISSING_CODE
    ) {
      throw error;
    }
    await runCommand("winget source reset", "winget", ["source", "reset", "--force"]);
    await installWindowsPackage(id, true);
  }
}

// Python is installed straight from the official python.org installer,
// downloaded over plain HTTPS (same downloadFile() used for the Silero
// weights below) and run silently — NOT through winget, unlike the other
// Windows packages above. A real affected user's setup.log showed winget
// itself is unusable on their machine even scoped to --source winget (see
// WINGET_SOURCE_DATA_MISSING_CODE) — and unlike LibreOffice/FFmpeg/
// Tesseract/Stockfish, Python isn't optional: runSetup can't create the
// venv or install a single pip dependency without it, so it can't be made
// non-fatal the way installWindowsPackages() is. Downloading the official
// installer directly sidesteps winget (and its source list / msstore
// agreement / admin-only reset) entirely for the one dependency that
// actually has to succeed.
//
// InstallAllUsers=0 matches this app's whole per-user, no-admin-required
// install philosophy (see nsis.perMachine: false in electron-builder.yml);
// PrependPath=1 is what makes findSystemPython() succeed on the *next*
// launch, and findWindowsPythonAfterInstall() below covers this same
// already-running process not seeing the updated PATH yet.
async function installWindowsPython(onProgress: (fraction: number) => void): Promise<void> {
  const installerPath = path.join(userDataDir(), `python-${PYTHON_INSTALLER_VERSION}-amd64.exe`);
  await downloadFile(PYTHON_INSTALLER_URL, installerPath, onProgress);
  try {
    await runCommand("python.org installer", installerPath, [
      "/quiet",
      "InstallAllUsers=0",
      "PrependPath=1",
      "Include_launcher=0",
    ]);
  } finally {
    await fs.rm(installerPath, { force: true });
  }
}

function downloadFile(url: string, destPath: string, onProgress?: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = https.get(url, (response) => {
      const redirect = response.headers.location;
      if (response.statusCode && [301, 302, 303, 307, 308].includes(response.statusCode) && redirect) {
        response.resume();
        downloadFile(redirect, destPath, onProgress).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        reject(new Error(`Download failed: ${url} -> HTTP ${response.statusCode}`));
        return;
      }
      const total = Number(response.headers["content-length"] ?? 0);
      let received = 0;
      const file = createWriteStream(destPath);
      response.on("data", (chunk: Buffer) => {
        received += chunk.length;
        if (total > 0 && onProgress) {
          onProgress(received / total);
        }
      });
      response.pipe(file);
      file.on("finish", () => file.close(() => resolve()));
      file.on("error", reject);
    });
    request.on("error", reject);
  });
}

async function writeLinuxDesktopEntry(): Promise<void> {
  // AppImages don't self-register in the desktop's app menu the way an
  // NSIS install auto-creates Start Menu/Desktop shortcuts on Windows — this
  // is the one bit of Linux-side "shortcut" work this module has to do
  // itself. execPath is the AppImage's own path while running from one
  // (Electron sets process.env.APPIMAGE in that case); falls back to the
  // plain executable path otherwise (e.g. an extracted/non-AppImage build).
  const execPath = process.env.APPIMAGE || process.execPath;
  const iconsDir = path.join(process.env.HOME ?? "", ".local", "share", "icons");
  const appsDir = path.join(process.env.HOME ?? "", ".local", "share", "applications");
  await fs.mkdir(iconsDir, { recursive: true });
  await fs.mkdir(appsDir, { recursive: true });

  const bundledIcon = path.join(process.resourcesPath, "icon.png");
  const iconDest = path.join(iconsDir, "nabve1.png");
  await fs.copyFile(bundledIcon, iconDest).catch(() => {
    // Non-fatal — worst case the menu entry shows a generic icon.
  });

  const desktopEntry = [
    "[Desktop Entry]",
    "Type=Application",
    "Name=NABVE1",
    "Comment=Локальный голосовой ассистент",
    `Exec="${execPath}" %U`,
    `Icon=${iconDest}`,
    "Terminal=false",
    "Categories=Utility;",
  ].join("\n");
  await fs.writeFile(path.join(appsDir, "nabve1.desktop"), `${desktopEntry}\n`, "utf-8");
}

export async function runSetup(onProgress: (progress: SetupProgress) => void): Promise<void> {
  await fs.mkdir(userDataDir(), { recursive: true });
  await fs.mkdir(packagedDataDir(), { recursive: true });
  await fs.mkdir(packagedLogsDir(), { recursive: true });
  await appendSetupLog(`--- setup started ${new Date().toISOString()} ---`);

  let stockfishPath: string | null = null;

  onProgress({ step: "Проверяю Python...", percent: 5 });
  let pythonBin = await findSystemPython();

  if (process.platform === "linux") {
    onProgress({ step: "Устанавливаю системные пакеты (нужен пароль)...", percent: 15 });
    await installLinuxSystemPackages();
    if (!pythonBin) {
      pythonBin = await findSystemPython();
    }
  } else if (process.platform === "win32") {
    if (!pythonBin) {
      onProgress({ step: "Скачиваю Python...", percent: 8 });
      await installWindowsPython((fraction) => {
        onProgress({ step: "Скачиваю Python...", percent: 8 + Math.round(fraction * 7) });
      });
      pythonBin = (await findSystemPython()) ?? (await findWindowsPythonAfterInstall());
    }
    onProgress({ step: "Устанавливаю системные пакеты...", percent: 15 });
    await installWindowsPackages();
    stockfishPath = await findWindowsStockfishAfterInstall();
  }

  if (!pythonBin) {
    throw new Error(`Не удалось найти или установить Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+`);
  }

  onProgress({ step: "Создаю окружение Python...", percent: 30 });
  await runCommand("venv", pythonBin, ["-m", "venv", venvDir()]);

  const venvPython = venvPythonBin();
  const requirementsPath = path.join(backendResourcesDir(), "requirements.txt");

  onProgress({ step: "Устанавливаю зависимости (это может занять пару минут)...", percent: 45 });
  await runCommand("pip install requirements", venvPython, ["-m", "pip", "install", "-r", requirementsPath]);

  onProgress({ step: "Устанавливаю движок распознавания речи...", percent: 65 });
  await runCommand("pip install torch", venvPython, [
    "-m",
    "pip",
    "install",
    "--index-url",
    "https://download.pytorch.org/whl/cpu",
    "torch",
  ]);

  onProgress({ step: "Устанавливаю браузерный движок...", percent: 75 });
  await runCommand("playwright install", venvPython, ["-m", "playwright", "install", "chromium"]);

  onProgress({ step: "Скачиваю голосовую модель...", percent: 85 });
  const voicesDir = path.join(packagedDataDir(), "voices");
  await fs.mkdir(voicesDir, { recursive: true });
  const sileroPath = path.join(voicesDir, "silero_ru_v3.pt");
  const sileroAlreadyPresent = await fs
    .access(sileroPath)
    .then(() => true)
    .catch(() => false);
  if (!sileroAlreadyPresent) {
    await downloadFile(SILERO_WEIGHTS_URL, sileroPath, (fraction) => {
      onProgress({ step: "Скачиваю голосовую модель...", percent: 85 + Math.round(fraction * 8) });
    });
  }

  if (process.platform === "linux") {
    onProgress({ step: "Создаю ярлык в меню приложений...", percent: 95 });
    await writeLinuxDesktopEntry().catch((error: unknown) => {
      // Non-fatal: the app is fully usable without a menu entry, worth
      // logging but not worth failing the whole setup over.
      void appendSetupLog(`[desktop entry] failed: ${String(error)}`);
    });
  }

  await writeSetupState({ schemaVersion: SETUP_SCHEMA_VERSION, stockfishPath });
  await appendSetupLog(`--- setup finished ${new Date().toISOString()} ---`);
  onProgress({ step: "Готово", percent: 100 });
}

export function getSetupLogPath(): string {
  return setupLogPath();
}
