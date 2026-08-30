# NABVE — NEURAL ASSISTANT BROWSER VERSION 1

GitHub: https://github.com/Irestm/NABVE1

Download the built app (v0.1.0): [Windows .exe](https://github.com/Irestm/NABVE1/releases/download/v0.1.0/NABVE1.Setup.0.1.0.exe) · [all releases](https://github.com/Irestm/NABVE1/releases) — install instructions in [INSTALL.md](INSTALL.md) (Russian-only for now).

A local, single-user voice assistant ("Jarvis"): a FastAPI backend + an Electron/React interface, with hybrid AI (a local on-device model plus cloud providers as fallback) and a set of modules for controlling the computer.

---

## How it works

### The voice loop
`wake word → speech recognition → command → response`

1. The **wake word** (default "ассистент"/"assistant") wakes the loop — it's always listening in the background.
2. **Rules** (`core/voice/intent.py`) try to parse the phrase without AI first — fast and reliable for common commands (open/shutdown/restart/windows/media/planner/"what can you do").
3. If no rule matches, the phrase goes to the **AI classifier**, which decides whether it's a command or an ordinary question and extracts parameters.
4. The reply is spoken aloud (Silero/Piper), shaped by the **communication style** chosen during onboarding (affects both the wording and the voice's tempo/pitch).

### Local model + cloud
If the machine has an NVIDIA GPU (4GB+ VRAM), a **local model** (Qwen2.5, via a local [Ollama](https://ollama.com) server) is loaded and used for simple requests — fast, private, no internet required. It's unloaded from VRAM after 5 minutes of idling and reloaded on demand.

For complex requests (needing fresh/live information) or when the local model is unavailable or unsure, a chain of cloud providers is used instead, driven through a real, automated browser: **Gemini → ChatGPT → DeepSeek → Grok**, switching automatically when one hits its daily limit.

### "Open X" — resolving games and apps
Speech recognition often garbles names ("dead sells" instead of Dead Cells). The assistant scans what's actually installed (shortcuts/`.desktop` entries, Steam libraries), builds a short list of plausible matches, and hands it to the AI to pick from along with a confidence score. Confident — opens it right away; unsure — asks "Did you mean …?" first.

### Mood-based music and video
"Play some music" with nothing else specified prompts "What's your mood today?", picks a track/video based on the answer, and opens a YouTube search for it. Naming something specific up front ("open a video of cats") skips the question entirely.

### Planner
"Remind me to call mom on Friday" — the assistant works out what and when (including relative phrasing like "tomorrow" or "in an hour"), adds it to the calendar, and announces it out loud ahead of time. A dedicated "Planner" tab in the UI shows a month calendar, an upcoming-events list, and manual add/delete.

### Stop word
Set up during onboarding. Say it, and the assistant stops responding to anything and just waits in the background. Say the same word again, and it's active once more.

### Personal profile (set up on first run)
What to call you, what to call itself, communication style (polite / down-to-earth / aggressive / calm / with swearing / friendly / formal / humorous — affects both wording and the voice's tempo), voice (6 options, including a random one), and the stop word.

---

## Voice commands

| Say this | What happens |
|---|---|
| "Open steam" / "launch dead sells" | Opens the app/game (tolerates speech-recognition garbling) |
| "Play some music" / "open a video of cats" | Asks about your mood, or opens a YouTube search for the named topic right away |
| "Remind me to buy milk tomorrow morning" | Adds it to the planner, announces it out loud ahead of time |
| "What can you do?" / "help" | Describes its own capabilities |
| "Shut down the computer" / "restart the computer" | Shuts down/restarts (with confirmation) |
| "Show the window" / "hide the window" | Controls the UI window |
| "‹stop word›" | Pauses/resumes reacting to voice |
| "stop"/"quiet" while it's talking | Interrupts the current reply (barge-in) |
| Any ordinary question | Answered like a regular AI |

Plus: passwords, web search, file handling (docx/xlsx/pdf) — via separate modules, see `modules/`.

---

## Running it

**Regular users** who just want to install and run the packaged app (no
manual Python/venv/pip): grab the installer (`.exe` for Windows or
`.AppImage` for Linux) and see [INSTALL.md](INSTALL.md) — Russian-only for
now, since that's this project's primary audience, but the gist is: first
launch installs everything it needs silently in the background, no
terminal involved. The rest of this section is the from-source setup, for
developers/contributors.

### Requirements
- Python 3.12, Node.js 18+
- A microphone and speakers/headphones for speech I/O
- Optional: an NVIDIA GPU (4GB+ VRAM) for the local model
- System packages (Linux): `python3-tk python3-dev wmctrl xdotool brightnessctl playerctl libnotify-bin libreoffice ffmpeg tesseract-ocr tesseract-ocr-rus stockfish`
- `stockfish` is only needed for voice chess games (`modules/board_games`, "let's play a game of chess"); Russian draughts works with no system packages — py-draughts's engine is pure Python.
- `brightnessctl` powers voice screen-brightness control with real backlight adjustment. Its apt package ships a udev rule granting the `video` group write access to `/sys/class/backlight`, but you still have to add yourself to that group: `sudo usermod -aG video $USER`, then log out and back in. Without `brightnessctl` (or without that group) the adapter falls back to `xrandr --brightness`, a software gamma dim only (backlight power unchanged).
- Optional, for voice-driven UI actions (`modules/ui_automation` — "click X"/"type Y" in whatever app currently has focus):
  - Desktop apps: `sudo apt-get install python3-gi gir1.2-atspi-2.0`, then enable your desktop's accessibility bus (GNOME: Settings → Accessibility) and, for JetBrains IDEs specifically, that IDE's own **Settings → Appearance & Behavior → Accessibility → Support screen readers** — a separate toggle from the DE-wide one. See `scripts/atspi_smoke_test.py` to check whether a given app's UI is actually visible to AT-SPI before relying on this.
  - Chrome/Chromium tabs: launch the browser with `--remote-debugging-port=9222` (a dedicated shortcut/alias — this can't be attached to an already-running browser afterward). Override the port with `ASSISTANT_CHROME_CDP_PORT` if 9222 is taken.

### Backend
```bash
pip install -r requirements.txt
# CPU build of torch (for Silero TTS):
pip install --index-url https://download.pytorch.org/whl/cpu torch
# one-time, for the cloud AI providers:
playwright install chromium

python -m core.watchdog
```
The server comes up on `http://127.0.0.1:8756` (port configurable via `ASSISTANT_PORT`). `watchdog` supervises the process and restarts it if it crashes.

### Frontend (desktop app)
```bash
cd frontend
npm install
npm run dev        # development (Vite + Electron)
npm run build      # production build
npm run package    # build an installer (electron-builder)
```

### Useful environment variables
| Variable | Purpose |
|---|---|
| `ASSISTANT_WAKE_WORD` | The wake word (default "ассистент") |
| `ASSISTANT_HOST` / `ASSISTANT_PORT` / `ASSISTANT_BIND_HOST` | Server address and port |
| `ASSISTANT_WHISPER_MODEL` | Speech-recognition model size (`base` by default) |
| `ASSISTANT_SILERO_SPEAKER` | Default voice (can also be changed in settings) |
| `PORCUPINE_ACCESS_KEY` | Offline wake-word engine (optional) |
| `GROQ_API_KEY` | Free fast AI tier ahead of the cloud chain (optional) |
| `TELEGRAM_NOTIFY_BOT_TOKEN` / `TELEGRAM_NOTIFY_CHAT_ID` | Outbound Telegram notifications (battery, reminders, plugins awaiting review) — optional |

Data (what the assistant remembers about you, stored passwords, the calendar database) lives locally under `data/` and is encrypted at rest.
