FROM python:3.12-slim

ARG UID=1000
ARG GID=1000

# System packages needed for the *full* feature set (not just the bare API):
#   wmctrl        -> list_windows/focus_window (core/os_adapter/linux.py)
#   xdotool       -> get_active_window (core/os_adapter/linux.py)
#   libnotify-bin -> desktop notifications (modules/calendar/notifier.py)
#   ffmpeg        -> audio decoding for faster-whisper (voice STT, crm_transcribe)
#   libportaudio2 -> microphone capture (sounddevice)
#   libreoffice   -> file format conversion (modules/files/converter.py)
#   git           -> repo snapshot/rollback used by modules/plugin_agent/git_safety.py
#   xdg-utils     -> xdg-open fallback for open_application
#   dbus          -> client libs to reach the host's D-Bus (shutdown/reboot, keyring, notify-send)
#   curl          -> container healthcheck
#   xvfb          -> hidden display for ai_bridge's headed-but-invisible browser automation
#                    (modules/ai_bridge/virtual_display.py) — see requirements.txt's own note
# tkinter itself ships pre-built in the official python image, no extra apt
# package needed for it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wmctrl \
    xdotool \
    libnotify-bin \
    ffmpeg \
    libportaudio2 \
    libreoffice \
    git \
    xdg-utils \
    dbus \
    ca-certificates \
    curl \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# A real user (not a bare numeric UID passed via `docker run --user`) so
# $HOME resolves to something that exists and is writable. Without this,
# anything that computes a cache path via os.path.expanduser("~") (notably
# huggingface_hub, which faster-whisper uses to download its Whisper model
# on first STT call) silently misbehaves once the container runs as a UID
# with no /etc/passwd entry — a common source of unexplained 500s that only
# show up under Docker. Matches the host UID/GID by default (see
# docker-compose.yml's build.args) so files written to the bind-mounted
# ./data and ./logs stay owned by you, not root.
RUN groupadd -g "${GID}" appuser \
    && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installed as root into a fixed, world-readable path instead of the default
# ~/.cache/ms-playwright, so Playwright finds the same browser binaries
# whether it's invoked at build time (root) or at runtime (appuser) — those
# two would otherwise disagree since $HOME differs between them.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright-browsers

COPY . .
RUN chown -R appuser:appuser /app

# faster-whisper (STT, used by voice queries, wake word, crm_transcribe)
# downloads its CTranslate2 model from Hugging Face on first use. Pointing
# its cache at the bind-mounted data/ dir means it survives container
# rebuilds instead of silently failing to write under an ephemeral $HOME, and
# doesn't re-download ~250MB+ on every restart.
ENV HF_HOME=/app/data/.cache/huggingface
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8756

CMD ["python", "-m", "core.watchdog"]
