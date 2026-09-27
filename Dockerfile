# syntax=docker/dockerfile:1.7

# Stage 1 — the React UI, built once and served by FastAPI from frontend/dist
# (core/main.py mounts it at "/"), so the browser at http://127.0.0.1:8756
# gets the same interface as the Electron shell.
FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build:vite

# Stage 2 — Python dependencies in an isolated virtualenv, so the runtime
# image gets them as a single COPY without pip, caches or build leftovers.
FROM python:3.12-slim-bookworm AS python-deps
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG SPACY_MODEL=en_core_web_sm
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv "$VIRTUAL_ENV"
# CPU torch is enough for Silero TTS (see requirements.txt); installing it
# first keeps pip from pulling the multi-GB CUDA build as a transitive default.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url "$TORCH_INDEX_URL" "torch>=2.0,<3"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && python -m spacy download "$SPACY_MODEL"

# Stage 3 — runtime.
FROM python:3.12-slim-bookworm AS runtime

ARG UID=1000
ARG GID=1000

# System packages needed for the full feature set, not just the bare API:
#   wmctrl, xdotool       -> window listing/focus (core/os_adapter/linux.py)
#   brightnessctl         -> screen brightness, xrandr fallback otherwise
#   playerctl             -> pause/resume media (critical reminders)
#   power-profiles-daemon -> powerprofilesctl client for power profiles
#   libnotify-bin         -> desktop notifications (modules/calendar/notifier.py)
#   ffmpeg                -> faster-whisper decoding, English listening clips
#   libportaudio2         -> microphone capture (sounddevice)
#   libasound2-plugins    -> ALSA -> host PulseAudio/PipeWire bridge (docker/asound.conf)
#   libreoffice           -> office suite bridge and file conversion
#   git                   -> modules/plugin_agent/git_safety.py snapshots
#   xdg-utils, dbus       -> xdg-open fallback, host D-Bus (shutdown, keyring)
#   xvfb                  -> hidden display for ai_bridge browser automation
#   tesseract-ocr(-rus)   -> screen OCR
#   stockfish             -> voice chess (modules/board_games)
#   curl                  -> container healthcheck
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        wmctrl xdotool brightnessctl playerctl power-profiles-daemon libnotify-bin \
        ffmpeg libportaudio2 libasound2-plugins libreoffice git xdg-utils dbus ca-certificates curl xvfb \
        tesseract-ocr tesseract-ocr-rus stockfish

# A real account instead of a bare numeric UID so $HOME exists — huggingface_hub
# (faster-whisper model download) and Playwright both resolve paths from it.
# Matches the host UID/GID so files written to the bind-mounted ./data stay yours.
RUN groupadd -g "${GID}" appuser \
    && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash appuser

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH:/usr/games \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    HF_HOME=/app/data/.cache/huggingface

COPY --from=python-deps /opt/venv /opt/venv
COPY docker/asound.conf /etc/asound.conf

# Browser binaries in a fixed world-readable path, so build time (root) and
# runtime (appuser) agree on where Playwright finds Chromium.
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright-browsers \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --chown=appuser:appuser . .
COPY --from=frontend --chown=appuser:appuser /build/dist ./frontend/dist
RUN mkdir -p data logs && chown appuser:appuser data logs && chmod +x docker/entrypoint.sh

USER appuser

EXPOSE 8756

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 CMD ["docker/healthcheck.sh"]

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["python", "-m", "core.watchdog"]
